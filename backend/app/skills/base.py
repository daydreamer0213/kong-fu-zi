"""
Skill 定义 — 可插拔的对话能力模块

Skill 的核心思想（面试可讲）：
  大模型是"什么都能聊"的通用引擎，但生产环境需要可控、可预期的工作单元。
  Skill = 把通用能力封装成"角色+工具+规则"的组合包。

这和 Claude Code 的 Skill 系统、OpenAI GPTs 的设计理念一致：
  - 每个 Skill 是一个独立的能力域
  - Skill 之间互不干扰，可以独立增删
  - 用户选择一个 Skill = 进入一个特定的对话模式

三个内置 Skill：
  teaching: 夫子教诲（默认）— 循循善诱，点到即止
  poetry:   诗词赏析 — 以《诗经》诠释为主的鉴赏模式
  debate:   经学辩论 — 严谨引经据典，多方考证
"""

from dataclasses import dataclass, field


@dataclass
class Skill:
    """一个对话能力模块。

    Attributes:
        name: 内部标识，如 "teaching", "poetry", "debate"
        display_name: 展示名称，如 "夫子教诲", "诗词赏析"
        description: 一句话说明
        system_prompt: 该 Skill 下的 System Prompt
        allowed_tools: 可用工具名列表，空列表 = 全部可用
        icon: 图标标识（前端展示用）
        is_default: 是否为默认 Skill
    """

    name: str
    display_name: str
    description: str
    system_prompt: str
    allowed_tools: list[str] = field(default_factory=list)  # [] 表示全部可用
    icon: str = ""
    is_default: bool = False
