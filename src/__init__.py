"""
金蝶苍穹星瀚平台5.0 AI辅助开发知识库系统
"""
from src.config import settings

settings.ensure_directories()

__version__ = settings.version
__all__ = ["settings"]
