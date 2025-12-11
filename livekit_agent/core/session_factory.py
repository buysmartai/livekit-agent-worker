"""
Session 工厂

创建和配置 AgentSession。
"""

from typing import Optional

from livekit.agents.voice import AgentSession, VoiceActivityVideoSampler
from livekit.plugins import silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from ..providers import LLMProviderFactory, TTSProviderFactory, STTProviderFactory
from ..config import get_settings
from ..utils.logger import get_logger

logger = get_logger("core.session_factory")


def create_session(
    voice_id: Optional[str] = None,
    elevenlabs_voice_id: Optional[str] = None,
    language: str = "en"
) -> AgentSession:
    """
    创建 AgentSession
    
    根据配置创建 STT、TTS、LLM 实例，并组装成 AgentSession。
    
    Args:
        voice_id: MiniMax voice_id，用于非中文语言
        elevenlabs_voice_id: ElevenLabs voice_id，用于中文语言
        language: 语言代码，如果以 zh 开头则使用 ElevenLabs TTS
        
    Returns:
        配置好的 AgentSession
        
    Examples:
        >>> session = create_session()
        >>> # 或使用自定义 voice_id 和语言
        >>> session = create_session(voice_id="minimax_voice", elevenlabs_voice_id="elevenlabs_voice", language="zh-CN")
    """
    settings = get_settings()
    
    logger.info("🔧 创建 AgentSession...")
    # language
    logger.info(f"   🌐 语言: {language}")
    
    # 创建 STT
    stt = STTProviderFactory.create(settings.stt)
    logger.info(f"   ✅ STT: {settings.stt.provider} / {settings.stt.model}")
    
    # 创建 TTS - 根据语言选择提供商
    is_chinese = language.lower().startswith("zh")
    if is_chinese:
        # 中文使用 MiniMax
        tts = TTSProviderFactory.create(settings.tts, voice_id)
        actual_voice_id = voice_id or settings.tts.default_voice_id
        logger.info(f"   ✅ TTS: {settings.tts.provider} (中文模式) / {actual_voice_id}")
    else:
        # 非中文使用 ElevenLabs
        from livekit.plugins import elevenlabs
        actual_elevenlabs_voice_id = elevenlabs_voice_id or "JBFqnCBsd6RMkjVDRZzb"  # 默认 voice
        tts = elevenlabs.TTS(
            voice_id=actual_elevenlabs_voice_id,
            model="eleven_turbo_v2_5",
        )
        logger.info(f"   ✅ TTS: elevenlabs / {actual_elevenlabs_voice_id}")
    
    # 创建 LLM
    llm = LLMProviderFactory.create(settings.llm)
    logger.info(f"   ✅ LLM: {settings.llm.provider} / {settings.llm.model}")
    
    # 创建 VAD (用于打断检测和噪音过滤)
    vad = silero.VAD.load(
        min_speech_duration=0.15,     # 最小语音持续时间（秒），过滤短噪音
        min_silence_duration=0.6,     # 静音多久算说话结束（秒）
        activation_threshold=0.6,     # 语音激活阈值，越高越不容易被噪音触发（0.5-0.9）
        sample_rate=16000,
    )

    logger.info("   ✅ VAD: silero (打断检测 + 噪音过滤, threshold=0.6)")

    # 创建 Turn Detector (智能轮次检测)
    turn_detector = MultilingualModel()
    logger.info("   ✅ TurnDetector: MultilingualModel (智能轮次检测)")

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
        vad=vad,  # VAD 支持打断和噪音过滤
        turn_detection=turn_detector,  # 智能轮次检测（基于语言理解判断用户是否说完）
        video_sampler=video_sampler,
    )
    
    logger.info("✅ AgentSession 创建完成")
    
    return session
