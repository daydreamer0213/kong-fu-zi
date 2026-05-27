"""
Skill 注册表 — 管理所有 Skill 的注册、查询

面试可讲的设计点：
  1. 单例模式 — 全局唯一，启动时注册，请求时只读
  2. 注册与使用分离 — builtin.py 只管定义，registry 只管存取
  3. 默认 Skill — 用户不选时自动回退到 teaching
  4. allowed_tools 过滤 — Skill 可以选择性禁用某些工具
     （如 poetry 模式没必要用 web_search，但可以用 hybrid_search 查诗经）
"""

import logging
from typing import Optional

from app.skills.base import Skill

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Skill 注册表（单例）。

    使用方式：
        registry = SkillRegistry()
        registry.register(teaching_skill)   # 启动时
        registry.register(poetry_skill)
        registry.register(debate_skill)

        skill = registry.get("poetry")      # 请求时
        all_skills = registry.list_all()    # 前端展示可选模式
    """

    def __init__(self):
        self._skills: dict[str, Skill] = {}
        self._default: Skill | None = None

    def register(self, skill: Skill):
        """注册一个 Skill。

        如果 skill.is_default=True，覆盖之前的默认值。
        同名 Skill 后注册的覆盖先注册的。

        注册时记录日志，方便排查"为什么某个 Skill 没生效"的问题。
        """
        self._skills[skill.name] = skill
        if skill.is_default:
            self._default = skill
        logger.info(
            "Skill 已注册: %s (%s), 工具数=%d, 默认=%s",
            skill.name, skill.display_name,
            len(skill.allowed_tools) if skill.allowed_tools else -1,  # -1 = 全部
            skill.is_default,
        )

    def get(self, name: str) -> Skill | None:
        """按名称获取 Skill，不存在返回 None。

        调用方（agent.py）拿到 None 时应回退到默认 Skill。
        """
        return self._skills.get(name)

    def get_default(self) -> Skill | None:
        """获取默认 Skill"""
        return self._default

    def list_all(self) -> list[Skill]:
        """返回所有已注册的 Skill 列表（用于前端展示）"""
        return list(self._skills.values())

    def resolve(self, name: str | None) -> Skill | None:
        """解析 Skill 名称：有则返回，无/None 则返回默认。

        agent.py 调用此方法——不关心名称来源，只拿到最终 Skill。
        """
        if name:
            skill = self._skills.get(name)
            if skill:
                return skill
            logger.warning("Skill '%s' 不存在，回退到默认", name)
        return self._default


# 全局单例
_registry: SkillRegistry | None = None


def get_skill_registry() -> SkillRegistry:
    """获取全局 SkillRegistry 单例"""
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry
