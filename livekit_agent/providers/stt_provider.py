"""
STT 提供商工厂

支持多种 STT 提供商的动态切换。
"""

from enum import Enum
from typing import Any, Optional

from ..config import STTConfig
from ..utils.logger import get_logger

logger = get_logger("providers.stt")


class STTProvider(Enum):
    """STT 提供商枚举"""
    OPENAI = "openai"
    ALIYUN = "aliyun"


class STTProviderFactory:
    """STT 提供商工厂"""
    
    @staticmethod
    def create(config: STTConfig) -> Any:
        """
        根据配置创建 STT 实例
        
        Args:
            config: STT 配置
            
        Returns:
            STT 实例
            
        Raises:
            ValueError: 未知的提供商类型
            
        Examples:
            >>> config = STTConfig(
            ...     provider="openai",
            ...     model="gpt-4o-mini-transcribe",
            ...     use_realtime=True
            ... )
            >>> stt = STTProviderFactory.create(config)
        """
        provider = config.provider.lower()
        kwargs = config.to_kwargs()
        
        logger.info(f"🎤 创建 STT 实例: provider={provider}, model={config.model}")
        
        if provider == STTProvider.OPENAI.value:
            from livekit.plugins import openai
            return openai.STT(**kwargs)
        
        elif provider == STTProvider.ALIYUN.value:
            from livekit.plugins import aliyun
            return aliyun.STT(**kwargs)
        
        else:
            raise ValueError(f"Unknown STT provider: {provider}")
    
    @staticmethod
    def create_from_env() -> Any:
        """从环境变量创建 STT 实例"""
        from ..config import get_settings
        settings = get_settings()
        return STTProviderFactory.create(settings.stt)
