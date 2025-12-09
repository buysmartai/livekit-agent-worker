"""
TTS 提供商工厂

支持多种 TTS 提供商的动态切换。
"""

from enum import Enum
from typing import Any, Optional

from ..config import TTSConfig
from ..utils.logger import get_logger

logger = get_logger("providers.tts")


class TTSProvider(Enum):
    """TTS 提供商枚举"""
    MINIMAX = "minimax"
    ELEVENLABS = "elevenlabs"
    ALIYUN = "aliyun"


class TTSProviderFactory:
    """TTS 提供商工厂"""
    
    @staticmethod
    def create(config: TTSConfig, voice_id: Optional[str] = None) -> Any:
        """
        根据配置创建 TTS 实例
        
        Args:
            config: TTS 配置
            voice_id: 可选的 voice_id，覆盖配置中的默认值
            
        Returns:
            TTS 实例
            
        Raises:
            ValueError: 未知的提供商类型
            
        Examples:
            >>> config = TTSConfig(
            ...     provider="minimax",
            ...     default_voice_id="moss_audio_xxx",
            ...     model="speech-2.6-turbo"
            ... )
            >>> tts = TTSProviderFactory.create(config)
            >>> # 或使用自定义 voice_id
            >>> tts = TTSProviderFactory.create(config, voice_id="custom_voice")
        """
        provider = config.provider.lower()
        actual_voice_id = voice_id or config.default_voice_id
        kwargs = config.to_kwargs()
        
        logger.info(f"🔊 创建 TTS 实例: provider={provider}, voice_id={actual_voice_id}")
        
        if provider == TTSProvider.MINIMAX.value:
            from livekit.plugins.minimax_tts import TTS as MiniMaxTTS
            return MiniMaxTTS(
                voice_id=actual_voice_id,
                **kwargs,
            )
        
        elif provider == TTSProvider.ELEVENLABS.value:
            from livekit.plugins import elevenlabs
            return elevenlabs.TTS(
                voice_id=actual_voice_id,
                model=kwargs.get("model", "eleven_turbo_v2_5"),
            )
        
        elif provider == TTSProvider.ALIYUN.value:
            from livekit.plugins import aliyun
            return aliyun.TTS(
                voice=actual_voice_id,
                **kwargs,
            )
        
        else:
            raise ValueError(f"Unknown TTS provider: {provider}")
    
    @staticmethod
    def create_from_env(voice_id: Optional[str] = None) -> Any:
        """从环境变量创建 TTS 实例"""
        from ..config import get_settings
        settings = get_settings()
        return TTSProviderFactory.create(settings.tts, voice_id)
