"""
LiveKit Agent Worker - 模块化语音助手服务

该包提供了一个可扩展的语音助手框架，支持：
- 多提供商 LLM/TTS/STT 切换
- 视频多模态分析
- 动态 prompt 注入
- REST API 集成
"""

from .config import get_settings, Settings
from .core import VisionAgent, create_session, entrypoint

__version__ = "1.0.0"

__all__ = [
    "VisionAgent",
    "create_session",
    "entrypoint",
    "get_settings",
    "Settings",
]
