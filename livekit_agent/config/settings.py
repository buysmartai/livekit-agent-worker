"""
配置管理模块

从环境变量加载所有配置，支持不同服务提供商的灵活切换。
"""

from dataclasses import dataclass, field
from typing import Optional
import os


@dataclass
class APIConfig:
    """API 配置"""
    base_url: str
    api_key: str
    timeout: float = 10.0
    
    @property
    def is_valid(self) -> bool:
        """检查配置是否有效"""
        return bool(self.base_url and self.api_key)


@dataclass
class LLMConfig:
    """LLM 配置"""
    provider: str  # "openai", "google_gemini", "gemini_via_openai", "grok"
    model: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    reasoning_effort: Optional[str] = None  # "minimal", "low", "medium", "high" - Gemini 2.5+/3 专用
    
    def to_kwargs(self) -> dict:
        """转换为 LLM 构造参数"""
        kwargs = {"model": self.model}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        return kwargs


@dataclass
class TTSConfig:
    """TTS 配置"""
    provider: str  # "minimax", "elevenlabs", "aliyun"
    default_voice_id: str
    model: str = "speech-2.6-turbo"
    speed: float = 1.0
    volume: float = 1.0
    pitch: int = 0
    
    def to_kwargs(self) -> dict:
        """转换为 TTS 构造参数"""
        return {
            "model": self.model,
            "speed": self.speed,
            "volume": self.volume,
            "pitch": self.pitch,
        }


@dataclass
class STTConfig:
    """STT 配置"""
    provider: str  # "openai", "aliyun"
    model: str
    use_realtime: bool = True
    language: Optional[str] = None
    
    def to_kwargs(self) -> dict:
        """转换为 STT 构造参数"""
        kwargs = {"model": self.model, "use_realtime": self.use_realtime}
        if self.language:
            kwargs["language"] = self.language
        return kwargs


@dataclass
class AudioConfig:
    """音频处理配置"""
    denoise_enabled: bool = False  # 默认关闭降噪（节省 CPU）
    denoise_strength: float = 0.5  # 降噪强度 0.0-1.0
    denoise_skip_frames: int = 2   # 每 N 帧处理一次（1=每帧，2=隔帧，0=禁用）
    n_fft: int = 256               # FFT 窗口大小（越小越快，256 比 512 快 4 倍）
    hop_length: int = 64           # 跳跃长度


@dataclass
class VideoConfig:
    """视频采样配置"""
    speaking_fps: float = 1.0
    silent_fps: float = 0.3
    inference_width: int = 512
    inference_height: int = 512


@dataclass
class Settings:
    """全局配置"""
    # API 配置
    chat_api: APIConfig
    vision_api: APIConfig
    
    # 提供商配置
    llm: LLMConfig
    tts: TTSConfig
    stt: STTConfig
    
    # 视频配置
    video: VideoConfig = field(default_factory=VideoConfig)
    
    # 音频配置
    audio: AudioConfig = field(default_factory=AudioConfig)
    
    # 其他配置
    timezone: str = "America/New_York"
    language: str = "en"
    
    @classmethod
    def from_env(cls) -> "Settings":
        """从环境变量加载配置"""
        return cls(
            # Chat API 配置
            chat_api=APIConfig(
                base_url=os.getenv("CHAT_API_BASE_URL", ""),
                api_key=os.getenv("CHAT_API_KEY", ""),
                timeout=float(os.getenv("CHAT_API_TIMEOUT", "10")),
            ),
            # Vision API 配置
            vision_api=APIConfig(
                base_url=os.getenv("SCREEN_ANALYSIS_API_BASE_URL", "https://147ai.com/v1/"),
                api_key=os.getenv("SCREEN_ANALYSIS_API_KEY", ""),
                timeout=float(os.getenv("SCREEN_ANALYSIS_TIMEOUT", "30")),
            ),
            # LLM 配置
            llm=LLMConfig(
                provider=os.getenv("LLM_PROVIDER", "gemini_via_openai"),
                model=os.getenv("LLM_MODEL", "gemini-3-pro-preview"),
                base_url=os.getenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"),
                api_key=os.getenv("GOOGLE_API_KEY") or os.getenv("LLM_API_KEY"),
                reasoning_effort=os.getenv("LLM_REASONING_EFFORT"),  # "minimal", "low", "medium", "high"
            ),
            # TTS 配置
            tts=TTSConfig(
                provider=os.getenv("TTS_PROVIDER", "minimax"),
                default_voice_id=os.getenv("TTS_DEFAULT_VOICE_ID", "moss_audio_23e7a6cf-0996-11f0-ab96-82dcc6ce9d69"),
                model=os.getenv("TTS_MODEL", "speech-2.6-turbo"),
                speed=float(os.getenv("TTS_SPEED", "1.0")),
                volume=float(os.getenv("TTS_VOLUME", "1.0")),
                pitch=int(os.getenv("TTS_PITCH", "0")),
            ),
            # STT 配置
            stt=STTConfig(
                provider=os.getenv("STT_PROVIDER", "openai"),
                model=os.getenv("STT_MODEL", "gpt-4o-mini-transcribe"),
                use_realtime=os.getenv("STT_USE_REALTIME", "true").lower() == "true",
                language=os.getenv("STT_LANGUAGE"),
            ),
            # 视频配置
            video=VideoConfig(
                speaking_fps=float(os.getenv("VIDEO_SPEAKING_FPS", "1.0")),
                silent_fps=float(os.getenv("VIDEO_SILENT_FPS", "0.3")),
                inference_width=int(os.getenv("VIDEO_INFERENCE_WIDTH", "512")),
                inference_height=int(os.getenv("VIDEO_INFERENCE_HEIGHT", "512")),
            ),
            # 音频配置
            audio=AudioConfig(
                denoise_enabled=os.getenv("AUDIO_DENOISE_ENABLED", "false").lower() == "true",
                denoise_strength=float(os.getenv("AUDIO_DENOISE_STRENGTH", "0.5")),
                denoise_skip_frames=int(os.getenv("AUDIO_DENOISE_SKIP_FRAMES", "2")),
                n_fft=int(os.getenv("AUDIO_DENOISE_NFFT", "256")),
                hop_length=int(os.getenv("AUDIO_DENOISE_HOP_LENGTH", "64")),
            ),
            # 其他配置
            timezone=os.getenv("TIMEZONE", "America/New_York"),
            language=os.getenv("LANGUAGE", "en"),
        )


# 全局配置单例
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """获取全局配置（单例模式）"""
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings


def reload_settings() -> Settings:
    """重新加载配置（用于测试或热更新）"""
    global _settings
    _settings = Settings.from_env()
    return _settings
