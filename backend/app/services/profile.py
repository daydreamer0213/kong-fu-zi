"""
用户画像提取 — 对话结束后自动分析用户特征

和 Memory（remember/recall）的分工：
  - Memory: 用户主动要求记住的信息（"帮我记住xxx"），Agent 对话中自主检索
  - Profile: 系统自动从对话中提取的用户画像，注入 System Prompt 让角色感知用户

画像提取的 LLM 调用特点：
  - 低频：每轮对话都调，但多数返回空（无新增信息）
  - 低 token：T=0.1, max_tokens=200，一次几分钱
  - 结构化输出 JSON，程序解析后 merge 到现有画像

Token 预算控制（面试可讲）：
  - 画像注入上限 ~200 chars（约 50 tokens）
  - 只取 top-3 最重要的 facts + identity，每条截断在 30 字
  - 相比 System Prompt（~800 tokens），画像开销 < 6%
  - 如果画像过长→定期清理不活跃条目→具体用"最后提及时间"淘汰
"""

import json
import logging

from app.config import settings

logger = logging.getLogger(__name__)

# 提取 Prompt — 低温度、结构化输出、严格限定提取范围
_EXTRACTION_PROMPT = """分析以下对话，提取关于用户的持久信息。

## 需要提取的信息类型
- identity: 用户的身份、职业、角色（如"学生"、"程序员"、"家长"）
- level: 用户的知识水平（如"入门"、"中级"、"精通"）
- preferences: 用户明确表达的偏好（如"喜欢白话解释"、"认为子路过于冲动"）
- context: 对后续对话有用的背景信息（如"正在备考"、"最近在读学而篇"）

## 不需要提取的信息
- 一次性提问（"仁是什么意思"）← 不是持久信息
- 临时寒暄
- 论语句子的具体内容
- 助手已经回答的问题

## 输出格式
严格输出 JSON，不包含任何其他文本：
{"identity": "", "level": "", "preferences": [], "context": ""}

如果本轮对话没有新的持久信息，输出：{"identity":"","level":"","preferences":[],"context":""}

## 对话
用户：{user_message}
助手：{assistant_reply}

JSON："""


def extract_profile(
    user_message: str,
    assistant_reply: str,
) -> dict:
    """从一轮对话中提取用户画像片段。

    返回空 dict 表示本轮没有新信息。
    此函数不负责 merge——merge 由 update_user_profile() 完成。
    """
    prompt = _EXTRACTION_PROMPT.replace("{user_message}", user_message)
    prompt = prompt.replace("{assistant_reply}", assistant_reply[:500])

    try:
        from app.llm.client import chat
        raw = chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=200,
        )
        return _parse_extraction(raw)
    except Exception:
        logger.exception("画像提取 LLM 调用失败")
        return {}


def _parse_extraction(raw: str) -> dict:
    """从 LLM 返回的文本中提取 JSON"""
    raw = raw.strip()
    # 去掉可能的 markdown 代码块标记
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        # 尝试找 JSON 子串
        import re
        match = re.search(r'\{[^{}]*\}', raw)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return {}


def merge_profile(existing: dict | None, new_fragment: dict) -> dict:
    """把新提取的画像片段合并到现有画像。

    Merge 规则：
      - identity/level: 新值覆盖旧值（人不会突然换身份）
      - preferences: 去重追加，上限 10 条
      - context: 新值覆盖（上下文应反映最新状态）
    """
    if existing is None:
        existing = {}

    # identity / level — 覆盖
    for key in ("identity", "level", "context"):
        val = new_fragment.get(key, "").strip()
        if val:
            existing[key] = val[:30]  # 每条截断 30 字

    # preferences — 去重追加
    prefs = list(existing.get("preferences", []))
    for p in new_fragment.get("preferences", []):
        p = p.strip()[:30]
        if p and p not in prefs:
            prefs.append(p)
    if prefs:
        existing["preferences"] = prefs[:10]  # 上限 10 条

    return existing


def format_profile_for_prompt(profile: dict | None, max_tokens_estimate: int = 200) -> str:
    """把画像 dict 格式化为 System Prompt 注入文本。

    控制 token 预算：
      - identity + level 优先保留
      - context 其次
      - preferences 取前 3 条
      - 总长度控制在 ~200 chars 以内
    """
    if not profile:
        return ""

    parts = []
    identity_level = []
    if profile.get("identity"):
        identity_level.append(profile["identity"])
    if profile.get("level"):
        identity_level.append(f"{profile['level']}水平")
    if identity_level:
        parts.append("、".join(identity_level))

    if profile.get("context"):
        parts.append(profile["context"])

    prefs = profile.get("preferences", [])
    if prefs:
        top_prefs = prefs[:3]
        parts.append("偏好：" + "；".join(top_prefs))

    if not parts:
        return ""

    text = "## 关于提问者\n" + "。".join(parts) + "。"
    # 硬截断
    if len(text) > max_tokens_estimate:
        text = text[:max_tokens_estimate - 3] + "..."

    return text
