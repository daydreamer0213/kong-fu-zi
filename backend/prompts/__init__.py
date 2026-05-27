"""
集中式 Prompt 管理 — YAML 定义 + 元数据 + 版本追踪

面试可讲的设计点：
  1. 关注点分离：Prompt 内容和调用逻辑分开，非技术人员可修改 Prompt
  2. 版本化：每次改 Prompt 改 version，回滚和 A/B 测试都有据可查
  3. 元数据绑定：model + temperature + max_tokens 和 Prompt 绑定，调用方引用即可
  4. 对比分散式：当前项目 10 个 Prompt 散在 6 个文件里——
     大部分是"嵌在代码中的 Prompt"（如 Skill 定义、MCP 工具描述），
     这里只抽取"独立任务类 Prompt"（摘要、画像）做集中管理示范，
     展示"知道什么时候该集中、什么时候保持就近"的判断力
"""

import logging
import os
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


class PromptTemplate:
    """一个 Prompt 模板实例"""

    def __init__(self, name: str, data: dict):
        self.name = name
        self.version = data.get("version", 1)
        self.model = data.get("model", "deepseek-chat")
        self.temperature = data.get("temperature", 0.5)
        self.max_tokens = data.get("max_tokens", 512)
        self.template = data.get("template", "")

    def format(self, **kwargs) -> str:
        """用 .format() 风格填充模板占位符。和 str.format 兼容。"""
        return self.template.format(**kwargs)

    def __repr__(self):
        return f"PromptTemplate({self.name} v{self.version}, T={self.temperature})"


class PromptRegistry:
    """从 prompts/ 目录加载 YAML 文件，按名称提供 PromptTemplate。

    用法：
        registry = PromptRegistry("/path/to/prompts")
        tpl = registry.get("summary")
        prompt = tpl.format(existing="...", new_messages="...")
    """

    def __init__(self, directory: str | None = None):
        if directory is None:
            directory = os.path.join(os.path.dirname(__file__))
        self._directory = Path(directory)
        self._templates: dict[str, PromptTemplate] = {}
        self._load_all()

    def _load_all(self):
        for yaml_file in self._directory.glob("*.yaml"):
            try:
                with open(yaml_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                name = yaml_file.stem  # 文件名即 Prompt 名称
                self._templates[name] = PromptTemplate(name, data)
                logger.debug(
                    "Prompt 已加载: %s v%d (T=%.1f, max=%d)",
                    name, data.get("version", 1),
                    data.get("temperature", 0.5),
                    data.get("max_tokens", 512),
                )
            except Exception:
                logger.exception("Prompt 加载失败: %s", yaml_file)

    def get(self, name: str) -> PromptTemplate | None:
        return self._templates.get(name)

    def list_all(self) -> list[str]:
        return list(self._templates.keys())


# 全局单例——启动时加载一次
_registry: PromptRegistry | None = None


def get_prompt_registry() -> PromptRegistry:
    global _registry
    if _registry is None:
        _registry = PromptRegistry()
    return _registry
