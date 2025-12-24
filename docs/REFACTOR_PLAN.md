# LiveKit Agent Worker 重构方案

> 文档版本: v1.0  
> 创建日期: 2025-12-09  
> 作者: GitHub Copilot

## 1. 现状分析

### 1.1 当前代码结构

```
livekit-agent-worker/
├── agent.py                      # 主入口文件 (1410 行，过于庞大)
├── requirements.txt              # 依赖
├── deploy.sh                     # 部署脚本
├── docker-compose.yml            # Docker 配置
├── Dockerfile                    # Docker 镜像
└── livekit-plugins-minimax-tts/  # 已模块化的 TTS 插件（参考）
```

### 1.2 agent.py 职责分析

当前 `agent.py` 文件包含 **6+ 个独立职责**，严重违反单一职责原则：

| 职责模块 | 行数范围 | 预估行数 | 描述 |
|----------|----------|----------|------|
| **HTTP API 客户端** | 381-700 | ~320 行 | 4 个 API 方法，重复的错误处理 |
| **视频处理** | 分散 | ~150 行 | 帧管理、轨道处理、图像编码 |
| **LLM 节点处理** | 700-1000 | ~200 行 | 动态 prompt、上下文构建 |
| **延迟统计** | 130-220 | ~90 行 | 性能监控和日志 |
| **用户上下文管理** | 221-300 | ~100 行 | 房间名称解析、用户信息 |
| **事件处理** | 1160-1310 | ~150 行 | conversation_item_added 等 |
| **入口与配置** | 1000-1160 | ~160 行 | entrypoint、Session 配置 |

### 1.3 存在的问题

1. **单一职责违反**: 1410 行代码包含 6+ 个独立职责
2. **高耦合**: HTTP 客户端、视频处理、LLM 逻辑混在一起
3. **难以测试**: 无法单独测试各个组件
4. **难以扩展**: 添加新的 API 或服务需要修改核心文件
5. **重复代码**: API 调用有大量重复的错误处理和日志逻辑
6. **配置硬编码**: TTS/LLM/STT 提供商硬编码，无法灵活切换

---

## 2. 目标架构

### 2.1 设计原则

- **单一职责**: 每个模块只负责一个功能领域
- **开闭原则**: 对扩展开放，对修改关闭（通过策略/工厂模式）
- **依赖倒置**: 依赖抽象而非具体实现
- **可测试性**: 每个模块可独立单元测试

### 2.2 目标目录结构

```
livekit-agent-worker/
├── agent.py                        # 精简后的入口 (~100 行)
├── requirements.txt
├── docs/
│   └── REFACTOR_PLAN.md            # 本文档
│
├── livekit_agent/                  # 主包目录
│   ├── __init__.py
│   │
│   ├── core/                       # 核心模块
│   │   ├── __init__.py
│   │   ├── vision_agent.py         # VisionAgent 核心类 (~250 行)
│   │   ├── session_factory.py      # AgentSession 工厂
│   │   └── events.py               # 事件处理函数
│   │
│   ├── services/                   # 服务层（HTTP API 客户端）
│   │   ├── __init__.py
│   │   ├── base_client.py          # HTTP 客户端基类
│   │   ├── chat_api.py             # Chat API (getChatPrompt, saveGptResult)
│   │   ├── user_api.py             # User API (queryUserAvatarById)
│   │   └── vision_api.py           # 视觉分析 API
│   │
│   ├── providers/                  # 提供商工厂（策略模式）
│   │   ├── __init__.py
│   │   ├── llm_provider.py         # LLM 提供商工厂
│   │   ├── tts_provider.py         # TTS 提供商工厂
│   │   └── stt_provider.py         # STT 提供商工厂
│   │
│   ├── video/                      # 视频处理模块
│   │   ├── __init__.py
│   │   ├── frame_manager.py        # 视频帧管理
│   │   └── track_processor.py      # 视频轨道处理
│   │
│   ├── llm/                        # LLM 处理模块
│   │   ├── __init__.py
│   │   ├── prompt_manager.py       # Prompt 管理
│   │   └── context_builder.py      # 上下文构建
│   │
│   ├── utils/                      # 工具模块
│   │   ├── __init__.py
│   │   ├── latency.py              # 延迟统计
│   │   ├── room_parser.py          # 房间名称解析
│   │   └── logger.py               # 日志配置
│   │
│   ├── models/                     # 数据模型
│   │   ├── __init__.py
│   │   ├── user_context.py         # 用户上下文
│   │   └── api_response.py         # API 响应模型
│   │
│   └── config/                     # 配置管理
│       ├── __init__.py
│       └── settings.py             # 环境变量和配置
│
└── livekit-plugins-minimax-tts/    # 已有的 TTS 插件
```

### 2.3 各模块预估行数

| 模块 | 文件 | 预估行数 | 职责 |
|------|------|----------|------|
| 入口 | `agent.py` | ~100 | 程序入口，CLI 启动 |
| 核心 | `core/vision_agent.py` | ~250 | VisionAgent 核心逻辑 |
| 核心 | `core/session_factory.py` | ~100 | Session 配置工厂 |
| 核心 | `core/events.py` | ~100 | 事件处理 |
| 服务 | `services/base_client.py` | ~80 | HTTP 客户端基类 |
| 服务 | `services/chat_api.py` | ~120 | Chat API |
| 服务 | `services/user_api.py` | ~60 | User API |
| 服务 | `services/vision_api.py` | ~80 | Vision API |
| 提供商 | `providers/llm_provider.py` | ~80 | LLM 工厂 |
| 提供商 | `providers/tts_provider.py` | ~80 | TTS 工厂 |
| 提供商 | `providers/stt_provider.py` | ~60 | STT 工厂 |
| 视频 | `video/frame_manager.py` | ~80 | 帧管理 |
| 视频 | `video/track_processor.py` | ~50 | 轨道处理 |
| LLM | `llm/prompt_manager.py` | ~80 | Prompt 管理 |
| LLM | `llm/context_builder.py` | ~60 | 上下文构建 |
| 工具 | `utils/latency.py` | ~80 | 延迟统计 |
| 工具 | `utils/room_parser.py` | ~40 | 房间解析 |
| 工具 | `utils/logger.py` | ~30 | 日志配置 |
| 模型 | `models/user_context.py` | ~40 | 数据模型 |
| 模型 | `models/api_response.py` | ~40 | API 响应 |
| 配置 | `config/settings.py` | ~60 | 配置管理 |

**总计**: ~1700 行（因为增加了抽象层和类型定义，略有增加，但每个文件都短小精悍）

---

## 3. 核心设计详解

### 3.1 HTTP API 客户端抽象

```python
# services/base_client.py
from abc import ABC, abstractmethod
from typing import Optional, Any
import httpx

class BaseAPIClient(ABC):
    """HTTP API 客户端基类"""
    
    def __init__(self, base_url: str, api_key: str, timeout: float = 10.0):
        self.base_url = base_url
        self.api_key = api_key
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=3.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
        )
    
    async def _request(
        self, 
        method: str, 
        endpoint: str, 
        data: Optional[dict] = None
    ) -> tuple[Optional[dict], float]:
        """
        发送 HTTP 请求
        
        Returns:
            (响应数据, 耗时毫秒)
        """
        # 统一的请求逻辑、错误处理、日志记录
        ...
    
    async def close(self):
        await self._client.aclose()


# services/chat_api.py
class ChatAPIClient(BaseAPIClient):
    """Chat 相关 API 客户端"""
    
    async def get_dynamic_prompt(
        self,
        user_text: str,
        user_id: str,
        avatar_id: str,
        session_id: str
    ) -> Optional[dict]:
        """获取动态 prompt"""
        ...
    
    async def save_gpt_result(
        self,
        gpt_result: str,
        pingback: dict,
        user_context: dict,
        screen_frame_text: Optional[str] = None,
        camera_frame_text: Optional[str] = None
    ) -> bool:
        """保存 GPT 结果"""
        ...
```

### 3.2 提供商工厂模式

```python
# providers/llm_provider.py
from enum import Enum
from typing import Any
from livekit.plugins import openai, google

class LLMProvider(Enum):
    OPENAI = "openai"
    GOOGLE_GEMINI = "google_gemini"
    GEMINI_VIA_OPENAI = "gemini_via_openai"
    GROK = "grok"

class LLMProviderFactory:
    """LLM 提供商工厂"""
    
    @staticmethod
    def create(
        provider: LLMProvider,
        model: str,
        **config
    ) -> Any:  # 返回 LLM 实例
        """
        根据配置创建 LLM 实例
        
        Args:
            provider: 提供商类型
            model: 模型名称
            **config: 其他配置（api_key, base_url 等）
        
        Examples:
            # 使用 OpenAI 兼容模式调用 Gemini
            llm = LLMProviderFactory.create(
                provider=LLMProvider.GEMINI_VIA_OPENAI,
                model="gemini-3-pro-preview",
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                api_key=os.getenv("GOOGLE_API_KEY")
            )
            
            # 使用原生 Google LLM
            llm = LLMProviderFactory.create(
                provider=LLMProvider.GOOGLE_GEMINI,
                model="gemini-2.5-flash",
                thinking_config={"thinking_budget": 0}
            )
        """
        if provider == LLMProvider.OPENAI:
            return openai.LLM(model=model, **config)
        elif provider == LLMProvider.GOOGLE_GEMINI:
            return google.LLM(model=model, **config)
        elif provider == LLMProvider.GEMINI_VIA_OPENAI:
            return openai.LLM(model=model, **config)
        elif provider == LLMProvider.GROK:
            return openai.LLM(model=model, **config)
        else:
            raise ValueError(f"Unknown LLM provider: {provider}")


# providers/tts_provider.py
from enum import Enum

class TTSProvider(Enum):
    MINIMAX = "minimax"
    ELEVENLABS = "elevenlabs"
    ALIYUN = "aliyun"

class TTSProviderFactory:
    """TTS 提供商工厂"""
    
    @staticmethod
    def create(
        provider: TTSProvider,
        voice_id: str,
        **config
    ) -> Any:
        """根据配置创建 TTS 实例"""
        if provider == TTSProvider.MINIMAX:
            from livekit.plugins.minimax_tts import TTS as MiniMaxTTS
            return MiniMaxTTS(
                voice_id=voice_id,
                model=config.get("model", "speech-2.6-turbo"),
                speed=config.get("speed", 1.0),
                volume=config.get("volume", 1.0),
                pitch=config.get("pitch", 0),
            )
        elif provider == TTSProvider.ELEVENLABS:
            from livekit.plugins import elevenlabs
            return elevenlabs.TTS(
                voice_id=voice_id,
                model=config.get("model", "eleven_turbo_v2_5"),
                voice_settings=config.get("voice_settings"),
            )
        elif provider == TTSProvider.ALIYUN:
            from livekit.plugins import aliyun
            return aliyun.TTS(
                voice=voice_id,
                **config
            )
        else:
            raise ValueError(f"Unknown TTS provider: {provider}")
```

### 3.3 延迟统计模块

```python
# utils/latency.py
from dataclasses import dataclass, field
from typing import Optional, Callable
import time
import logging

logger = logging.getLogger(__name__)

@dataclass
class LatencyMetrics:
    """延迟统计数据"""
    turn_id: int = 0
    start_time: float = 0.0
    api_latency_ms: float = 0.0
    llm_first_token_time: float = 0.0
    llm_complete_time: float = 0.0
    tts_start_time: float = 0.0
    user_text: str = ""
    
    def get_llm_ttft_ms(self) -> float:
        """获取 LLM 首 Token 延迟 (毫秒)"""
        if self.llm_first_token_time and self.start_time:
            return (self.llm_first_token_time - self.start_time) * 1000
        return 0.0
    
    def get_total_latency_ms(self) -> float:
        """获取总延迟 (毫秒)"""
        if self.tts_start_time and self.start_time:
            return (self.tts_start_time - self.start_time) * 1000
        return 0.0


class LatencyTracker:
    """延迟追踪器"""
    
    def __init__(self):
        self._current_turn_id: int = 0
        self._metrics: LatencyMetrics = LatencyMetrics()
        self._observers: list[Callable[[str, LatencyMetrics], None]] = []
    
    def add_observer(self, observer: Callable[[str, LatencyMetrics], None]):
        """添加观察者（用于扩展日志/监控）"""
        self._observers.append(observer)
    
    def start_turn(self, user_text: str = "") -> LatencyMetrics:
        """开始新的对话轮次"""
        self._current_turn_id += 1
        self._metrics = LatencyMetrics(
            turn_id=self._current_turn_id,
            start_time=time.perf_counter(),
            user_text=user_text
        )
        return self._metrics
    
    def record_api_latency(self, latency_ms: float):
        """记录 API 延迟"""
        self._metrics.api_latency_ms = latency_ms
    
    def record_llm_first_token(self):
        """记录 LLM 首 Token 时间"""
        self._metrics.llm_first_token_time = time.perf_counter()
        self._notify("llm_first_token")
    
    def record_llm_complete(self):
        """记录 LLM 完成时间"""
        self._metrics.llm_complete_time = time.perf_counter()
        self._notify("llm_complete")
    
    def record_tts_started(self):
        """记录 TTS 开始时间"""
        self._metrics.tts_start_time = time.perf_counter()
        self._notify("tts_started")
        self.log_metrics("complete")
    
    def log_metrics(self, stage: str = "complete"):
        """输出格式化的延迟统计日志"""
        m = self._metrics
        logger.info("")
        logger.info("=" * 70)
        logger.info(f"⏱️  [延迟统计] Turn #{m.turn_id} | Stage: {stage}")
        logger.info(f"📝 用户输入: {m.user_text[:30]}...")
        logger.info("-" * 70)
        logger.info(f"├─ 🌐 API 延迟:              {m.api_latency_ms:>8.2f} ms")
        logger.info(f"├─ 🚀 LLM TTFT:              {m.get_llm_ttft_ms():>8.2f} ms")
        logger.info(f"└─ 📊 总延迟:                {m.get_total_latency_ms():>8.2f} ms")
        logger.info("=" * 70)
    
    def _notify(self, event: str):
        """通知观察者"""
        for observer in self._observers:
            try:
                observer(event, self._metrics)
            except Exception as e:
                logger.error(f"Observer error: {e}")
```

### 3.4 配置管理

```python
# config/settings.py
from dataclasses import dataclass
from typing import Optional
import os

@dataclass
class APIConfig:
    """API 配置"""
    base_url: str
    api_key: str
    timeout: float = 10.0

@dataclass
class LLMConfig:
    """LLM 配置"""
    provider: str  # "openai", "google_gemini", "gemini_via_openai"
    model: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None

@dataclass
class TTSConfig:
    """TTS 配置"""
    provider: str  # "minimax", "elevenlabs", "aliyun"
    default_voice_id: str
    model: str = "speech-2.6-turbo"
    speed: float = 1.0

@dataclass
class STTConfig:
    """STT 配置"""
    provider: str  # "openai", "aliyun"
    model: str
    use_realtime: bool = True

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
    
    # 其他配置
    timezone: str = "America/New_York"
    language: str = "en"
    
    @classmethod
    def from_env(cls) -> "Settings":
        """从环境变量加载配置"""
        return cls(
            chat_api=APIConfig(
                base_url=os.getenv("CHAT_API_BASE_URL", ""),
                api_key=os.getenv("CHAT_API_KEY", ""),
            ),
            vision_api=APIConfig(
                base_url=os.getenv("SCREEN_ANALYSIS_API_BASE_URL", ""),
                api_key=os.getenv("SCREEN_ANALYSIS_API_KEY", ""),
                timeout=30.0,
            ),
            llm=LLMConfig(
                provider=os.getenv("LLM_PROVIDER", "gemini_via_openai"),
                model=os.getenv("LLM_MODEL", "gemini-3-pro-preview"),
                base_url=os.getenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"),
                api_key=os.getenv("GOOGLE_API_KEY"),
            ),
            tts=TTSConfig(
                provider=os.getenv("TTS_PROVIDER", "minimax"),
                default_voice_id=os.getenv("TTS_DEFAULT_VOICE_ID", "moss_audio_23e7a6cf-0996-11f0-ab96-82dcc6ce9d69"),
                model=os.getenv("TTS_MODEL", "speech-2.6-turbo"),
            ),
            stt=STTConfig(
                provider=os.getenv("STT_PROVIDER", "openai"),
                model=os.getenv("STT_MODEL", "gpt-4o-mini-transcribe"),
            ),
            timezone=os.getenv("TIMEZONE", "America/New_York"),
            language=os.getenv("LANGUAGE", "en"),
        )

# 全局配置单例
_settings: Optional[Settings] = None

def get_settings() -> Settings:
    """获取全局配置"""
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings
```

### 3.5 精简后的 VisionAgent

```python
# core/vision_agent.py
from livekit.agents.voice import Agent
from livekit.agents import llm

from ..services import ChatAPIClient, UserAPIClient, VisionAPIClient
from ..video import VideoFrameManager
from ..utils import LatencyTracker, RoomNameParser
from ..models import UserContext
from ..config import get_settings

class VisionAgent(Agent):
    """支持视觉分析的自定义 Agent"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        settings = get_settings()
        
        # 注入依赖
        self._chat_api = ChatAPIClient(settings.chat_api)
        self._user_api = UserAPIClient(settings.chat_api)
        self._vision_api = VisionAPIClient(settings.vision_api)
        self._frame_manager = VideoFrameManager()
        self._latency_tracker = LatencyTracker()
        self._room_parser = RoomNameParser()
        
        # 用户上下文
        self._user_context: UserContext = UserContext()
        self._last_pingback: dict | None = None
    
    def set_user_info_from_room_name(self, room_name: str) -> bool:
        """从房间名称解析用户信息"""
        self._user_context = self._room_parser.parse(room_name)
        return self._user_context.is_valid
    
    async def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: list[llm.FunctionTool],
        model_settings,
    ):
        """LLM 节点 - 核心处理逻辑（精简版）"""
        # 1. 开始延迟统计
        user_text = self._extract_user_text(chat_ctx)
        self._latency_tracker.start_turn(user_text)
        
        # 2. 获取动态 prompt
        prompt_result = await self._chat_api.get_dynamic_prompt(
            user_text=user_text,
            user_context=self._user_context
        )
        
        if prompt_result:
            self._update_system_prompt(chat_ctx, prompt_result)
            self._last_pingback = prompt_result.get("pingback")
        
        # 3. 添加视频帧
        self._add_video_frames_to_message(chat_ctx)
        
        # 4. 调用 LLM
        is_first_token = True
        async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
            if is_first_token:
                self._latency_tracker.record_llm_first_token()
                is_first_token = False
            yield chunk
        
        self._latency_tracker.record_llm_complete()
```

---

## 4. 实施计划

### 4.1 分阶段实施

#### Phase 1: 基础设施 (预计 2 小时)

**目标**: 创建基础模块，不影响现有功能

- [ ] 创建目录结构
- [ ] 实现 `config/settings.py` - 配置管理
- [ ] 实现 `utils/logger.py` - 日志配置
- [ ] 实现 `utils/latency.py` - 延迟统计
- [ ] 实现 `utils/room_parser.py` - 房间名称解析
- [ ] 实现 `models/user_context.py` - 数据模型

#### Phase 2: 服务层 (预计 2 小时)

**目标**: 抽取 HTTP API 客户端

- [ ] 实现 `services/base_client.py` - HTTP 客户端基类
- [ ] 实现 `services/chat_api.py` - Chat API
- [ ] 实现 `services/user_api.py` - User API
- [ ] 实现 `services/vision_api.py` - Vision API
- [ ] 编写单元测试

#### Phase 3: 提供商工厂 (预计 1.5 小时)

**目标**: 实现提供商策略模式

- [ ] 实现 `providers/llm_provider.py` - LLM 工厂
- [ ] 实现 `providers/tts_provider.py` - TTS 工厂
- [ ] 实现 `providers/stt_provider.py` - STT 工厂

#### Phase 4: 视频处理 (预计 1 小时)

**目标**: 抽取视频处理逻辑

- [ ] 实现 `video/frame_manager.py` - 帧管理
- [ ] 实现 `video/track_processor.py` - 轨道处理

#### Phase 5: 核心重构 (预计 2.5 小时)

**目标**: 重构 VisionAgent 和 entrypoint

- [ ] 实现 `core/vision_agent.py` - 精简版 VisionAgent
- [ ] 实现 `core/session_factory.py` - Session 工厂
- [ ] 实现 `core/events.py` - 事件处理
- [ ] 重构 `agent.py` - 精简入口

#### Phase 6: 测试与文档 (预计 1 小时)

- [ ] 集成测试
- [ ] 更新 README.md
- [ ] 更新部署脚本

### 4.2 时间估算

| 阶段 | 预计时间 | 优先级 |
|------|----------|--------|
| Phase 1: 基础设施 | 2 小时 | P0 |
| Phase 2: 服务层 | 2 小时 | P0 |
| Phase 3: 提供商工厂 | 1.5 小时 | P1 |
| Phase 4: 视频处理 | 1 小时 | P1 |
| Phase 5: 核心重构 | 2.5 小时 | P0 |
| Phase 6: 测试与文档 | 1 小时 | P1 |
| **总计** | **10 小时** | - |

---

## 5. 扩展点设计

### 5.1 支持多服务接入的策略

重构后，接入新服务只需要：

#### 添加新的 LLM 提供商

```python
# 1. 在 LLMProvider 枚举中添加新类型
class LLMProvider(Enum):
    ...
    CLAUDE = "claude"  # 新增

# 2. 在工厂中添加创建逻辑
if provider == LLMProvider.CLAUDE:
    from livekit.plugins import anthropic
    return anthropic.LLM(model=model, **config)

# 3. 配置环境变量
LLM_PROVIDER=claude
LLM_MODEL=claude-3-sonnet
```

#### 添加新的 TTS 提供商

```python
# 1. 在 TTSProvider 枚举中添加新类型
class TTSProvider(Enum):
    ...
    AZURE = "azure"  # 新增

# 2. 在工厂中添加创建逻辑
if provider == TTSProvider.AZURE:
    from livekit.plugins import azure
    return azure.TTS(voice=voice_id, **config)

# 3. 配置环境变量
TTS_PROVIDER=azure
```

#### 添加新的后端 API

```python
# 1. 创建新的 API 客户端类
# services/new_api.py
class NewAPIClient(BaseAPIClient):
    async def some_method(self, ...) -> Optional[dict]:
        return await self._request("POST", "/some/endpoint", data={...})

# 2. 在 VisionAgent 中注入
self._new_api = NewAPIClient(settings.new_api)
```

### 5.2 不同业务场景的配置示例

#### 场景 1: 国内服务（低延迟）

```env
# .env.china
LLM_PROVIDER=aliyun
LLM_MODEL=qwen-max
TTS_PROVIDER=aliyun
TTS_DEFAULT_VOICE_ID=zhixiaobai
STT_PROVIDER=aliyun
STT_MODEL=paraformer-realtime-v2
```

#### 场景 2: 海外服务（高质量）

```env
# .env.global
LLM_PROVIDER=gemini_via_openai
LLM_MODEL=gemini-3-pro-preview
TTS_PROVIDER=elevenlabs
TTS_DEFAULT_VOICE_ID=tQ4MEZFJOzsahSEEZtHK
STT_PROVIDER=openai
STT_MODEL=gpt-4o-mini-transcribe
```

#### 场景 3: 成本优先

```env
# .env.budget
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
TTS_PROVIDER=minimax
TTS_MODEL=speech-2.6-turbo
STT_PROVIDER=openai
STT_MODEL=whisper-1
```

---

## 6. 迁移指南

### 6.1 环境变量变更

| 旧变量 | 新变量 | 说明 |
|--------|--------|------|
| `GOOGLE_API_KEY` | `LLM_API_KEY` | LLM API 密钥 |
| - | `LLM_PROVIDER` | 新增：LLM 提供商 |
| - | `LLM_MODEL` | 新增：LLM 模型 |
| - | `TTS_PROVIDER` | 新增：TTS 提供商 |
| - | `STT_PROVIDER` | 新增：STT 提供商 |

### 6.2 向后兼容

为了向后兼容，`agent.py` 入口文件保持不变：

```python
# agent.py (重构后)
from dotenv import load_dotenv
from livekit.agents import WorkerOptions, cli
from livekit_agent.core import entrypoint

if __name__ == "__main__":
    load_dotenv()
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
```

现有的部署脚本 `deploy.sh`、`docker-compose.yml` 无需修改。

---

## 7. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 重构导致 bug | 高 | 分阶段实施，每阶段测试 |
| 性能下降 | 中 | 保留延迟统计，对比重构前后 |
| 部署问题 | 中 | 保持入口文件不变 |
| 依赖循环 | 低 | 严格分层，单向依赖 |

---

## 8. 总结

本次重构将 1410 行的单文件拆分为 ~20 个小文件，每个文件 50-120 行，实现：

1. **高内聚低耦合**: 每个模块职责单一
2. **可扩展**: 通过工厂模式支持多提供商
3. **可测试**: 每个模块可独立单测
4. **可配置**: 通过环境变量切换服务

重构后，接入新服务只需：
1. 添加枚举值
2. 添加工厂分支
3. 配置环境变量

无需修改核心业务逻辑。
