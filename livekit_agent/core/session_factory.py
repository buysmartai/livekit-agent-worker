"""
Session 工厂

创建和配置 AgentSession。
"""

from typing import Optional

from livekit.agents.voice import AgentSession, VoiceActivityVideoSampler

from ..providers import LLMProviderFactory, TTSProviderFactory, STTProviderFactory
from ..config import get_settings
from ..utils.logger import get_logger

logger = get_logger("core.session_factory")


def create_session(voice_id: Optional[str] = None) -> AgentSession:
    """
    创建 AgentSession
    
    根据配置创建 STT、TTS、LLM 实例，并组装成 AgentSession。
    
    Args:
        voice_id: 可选的 voice_id，覆盖默认配置
        
    Returns:
        配置好的 AgentSession
        
    Examples:
        >>> session = create_session()
        >>> # 或使用自定义 voice_id
        >>> session = create_session(voice_id="custom_voice")
    """
    settings = get_settings()
    
    logger.info("🔧 创建 AgentSession...")
    
    # 创建 STT
    stt = STTProviderFactory.create(settings.stt)
    logger.info(f"   ✅ STT: {settings.stt.provider} / {settings.stt.model}")
    
    # 创建 TTS
    tts = TTSProviderFactory.create(settings.tts, voice_id)
    actual_voice_id = voice_id or settings.tts.default_voice_id
    logger.info(f"   ✅ TTS: {settings.tts.provider} / {actual_voice_id}")
    
    # 创建 LLM
    llm = LLMProviderFactory.create(settings.llm)
    logger.info(f"   ✅ LLM: {settings.llm.provider} / {settings.llm.model}")
    
    # 创建视频采样器
    video_sampler = VoiceActivityVideoSampler(
        speaking_fps=settings.video.speaking_fps,
        silent_fps=settings.video.silent_fps,
    )
    logger.info(f"   ✅ VideoSampler: speaking_fps={settings.video.speaking_fps}, silent_fps={settings.video.silent_fps}")
    
    # 创建 Session
    session = AgentSession(
        stt=stt,
        tts=tts,
        llm=llm,
        video_sampler=video_sampler,
    )
    
    logger.info("✅ AgentSession 创建完成")
    
    return session
