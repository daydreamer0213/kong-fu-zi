"""Skill 机制单元测试"""
from app.skills.base import Skill
from app.skills.registry import SkillRegistry
from app.skills.builtin import (
    BUILTIN_SKILLS,
    teaching_skill,
    poetry_skill,
    debate_skill,
)


class TestSkillRegistry:
    def test_register_and_get(self):
        reg = SkillRegistry()
        reg.register(teaching_skill)
        found = reg.get("teaching")
        assert found is not None
        assert found.display_name == "夫子教诲"

    def test_get_nonexistent(self):
        reg = SkillRegistry()
        assert reg.get("nonexistent") is None

    def test_default_skill(self):
        reg = SkillRegistry()
        reg.register(teaching_skill)
        reg.register(poetry_skill)
        # teaching 的 is_default=True
        assert reg.get_default().name == "teaching"

    def test_resolve_by_name(self):
        reg = SkillRegistry()
        reg.register(teaching_skill)
        reg.register(poetry_skill)
        s = reg.resolve("poetry")
        assert s.name == "poetry"

    def test_resolve_none_returns_default(self):
        reg = SkillRegistry()
        reg.register(teaching_skill)
        assert reg.resolve(None).name == "teaching"

    def test_resolve_unknown_falls_back_to_default(self):
        reg = SkillRegistry()
        reg.register(teaching_skill)
        s = reg.resolve("unknown")
        assert s.name == "teaching"  # 回退

    def test_resolve_unknown_without_default(self):
        reg = SkillRegistry()
        assert reg.resolve("unknown") is None

    def test_list_all(self):
        reg = SkillRegistry()
        reg.register(teaching_skill)
        reg.register(poetry_skill)
        assert len(reg.list_all()) == 2

    def test_register_overwrites(self):
        reg = SkillRegistry()
        reg.register(teaching_skill)
        # overwrite
        reg.register(Skill(
            name="teaching", display_name="新版", description="",
            system_prompt="new prompt", is_default=False,
        ))
        assert reg.get("teaching").system_prompt == "new prompt"


class TestBuiltinSkills:
    def test_three_skills(self):
        assert len(BUILTIN_SKILLS) == 3

    def test_teaching_is_default(self):
        assert teaching_skill.is_default is True

    def test_teaching_has_all_tools(self):
        """空 allowed_tools 表示全部可用"""
        assert teaching_skill.allowed_tools == []

    def test_poetry_restricts_tools(self):
        """poetry 不应包含 web_search"""
        assert len(poetry_skill.allowed_tools) == 3
        assert "web_search" not in poetry_skill.allowed_tools

    def test_debate_has_all_tools(self):
        assert debate_skill.allowed_tools == []

    def test_skills_have_different_prompts(self):
        """三个 Skill 的 System Prompt 应各不相同"""
        prompts = {s.name: s.system_prompt for s in BUILTIN_SKILLS}
        assert prompts["teaching"] != prompts["poetry"]
        assert prompts["teaching"] != prompts["debate"]
        assert prompts["poetry"] != prompts["debate"]

    def test_prompts_contain_shared_persona(self):
        """每个 Prompt 应包含基础角色设定"""
        for s in BUILTIN_SKILLS:
            assert "孔子" in s.system_prompt
            assert "春秋" in s.system_prompt
            assert "非礼勿言" in s.system_prompt

    def test_poetry_prompt_mentions_shijing(self):
        assert "诗" in poetry_skill.system_prompt

    def test_debate_prompt_mentions_cross_reference(self):
        assert "交叉" in debate_skill.system_prompt or "互证" in debate_skill.system_prompt
