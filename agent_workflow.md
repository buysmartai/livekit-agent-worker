# LiveKit Agent Worker 工作流与模块调用关系

## 🏗️ 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                    agent.py (入口)                                    │
│                                         │                                            │
│                                   cli.run_app()                                      │
│                                         │                                            │
│                              WorkerOptions(entrypoint)                               │
└─────────────────────────────────────────┬───────────────────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           core/entrypoint.py (入口点函数)                             │
│  ┌────────────────────────────────────────────────────────────────────────────────┐ │
│  │  async def entrypoint(ctx: JobContext):                                        │ │
│  │    1. 创建 VisionAgent                                                         │ │
│  │    2. 解析房间名称 -> 获取 user_id, avatar_id                                   │ │
│  │    3. 获取 Avatar 语音配置 (voice_id)                                          │ │
│  │    4. 创建 AgentSession (STT + TTS + LLM)                                      │ │
│  │    5. 注册事件处理                                                              │ │
│  │    6. 启动会话                                                                  │ │
│  │    7. 连接房间                                                                  │ │
│  │    8. 设置视频轨道订阅                                                          │ │
│  └────────────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────┬───────────────────────────────────────────┘
                                          │
                    ┌─────────────────────┼─────────────────────┐
                    │                     │                     │
                    ▼                     ▼                     ▼
┌─────────────────────────┐  ┌─────────────────────────┐  ┌─────────────────────────┐
│   core/vision_agent.py  │  │ core/session_factory.py │  │  video/track_processor  │
│      (核心 Agent)        │  │    (Session 工厂)        │  │    (视频轨道处理)        │
└────────────┬────────────┘  └────────────┬────────────┘  └────────────┬────────────┘
             │                            │                            │
             │                            ▼                            │
             │               ┌─────────────────────────┐               │
             │               │      AgentSession       │               │
             │               │  ┌──────┐ ┌───┐ ┌───┐   │               │
             │               │  │ STT  │ │TTS│ │LLM│   │               │
             │               │  └──────┘ └───┘ └───┘   │               │
             │               │  + VoiceActivityVideo   │               │
             │               │       Sampler           │               │
             │               └─────────────────────────┘               │
             │                                                         │
             └─────────────────────────┬───────────────────────────────┘
                                       │
                                       ▼
```

## 📦 模块层次结构

```
livekit_agent/
├── config/
│   └── settings.py         # 配置管理 (从环境变量加载)
│       ├── APIConfig       # API 配置 (base_url, api_key)
│       ├── LLMConfig       # LLM 配置 (provider, model, base_url)
│       ├── TTSConfig       # TTS 配置 (provider, voice_id, model)
│       ├── STTConfig       # STT 配置 (provider, model)
│       └── VideoConfig     # 视频采样配置 (fps)
│
├── core/
│   ├── entrypoint.py       # LiveKit Agent 入口点
│   ├── session_factory.py  # AgentSession 工厂
│   └── vision_agent.py     # 核心 Agent (继承自 livekit.Agent)
│
├── providers/              # 服务提供商工厂 (多云支持)
│   ├── llm_provider.py     # LLM 工厂 (OpenAI/Gemini/Grok/阿里云)
│   ├── tts_provider.py     # TTS 工厂 (MiniMax/ElevenLabs/阿里云)
│   └── stt_provider.py     # STT 工厂 (OpenAI/阿里云)
│
├── services/               # 业务 API 客户端
│   ├── base_client.py      # HTTP 客户端基类
│   ├── chat_api.py         # Chat API (getChatPrompt, saveGptResult)
│   ├── user_api.py         # User API (获取 Avatar 配置)
│   └── vision_api.py       # Vision API (屏幕/摄像头分析)
│
├── video/                  # 视频处理模块
│   ├── frame_manager.py    # 视频帧管理器 (camera/screen_share)
│   └── track_processor.py  # LiveKit 视频轨道处理
│
├── models/                 # 数据模型
│   ├── user_context.py     # 用户上下文 (user_id, avatar_id, session_id)
│   └── api_response.py     # API 响应模型 (PromptResponse, PingbackData)
│
└── utils/                  # 工具函数
    ├── logger.py           # 日志工具
    ├── latency.py          # 延迟统计
    └── room_parser.py      # 房间名称解析
```

## 🔄 完整工作流

### 阶段 1: 启动与初始化

```
agent.py main()
    │
    ├─> load_dotenv()                    # 加载环境变量
    │
    └─> cli.run_app(WorkerOptions)       # 启动 LiveKit Worker
            │
            └─> entrypoint(ctx)          # 当有房间连接时触发
                    │
                    ├─> VisionAgent()    # 创建 Agent 实例
                    │       │
                    │       ├─> ChatAPIClient
                    │       ├─> UserAPIClient  
                    │       ├─> VisionAPIClient
                    │       ├─> VideoFrameManager
                    │       └─> LatencyTracker
                    │
                    ├─> 解析房间名称      # user_id, avatar_id, timestamp
                    │
                    ├─> get_avatar_voice_info()  # 获取语音配置
                    │
                    └─> create_session()  # 创建 AgentSession
                            │
                            ├─> STTProviderFactory.create()
                            ├─> TTSProviderFactory.create()
                            ├─> LLMProviderFactory.create()
                            └─> VoiceActivityVideoSampler()
```

### 阶段 2: 会话运行时

```
session.start(agent, room)
    │
    └─> ctx.connect()                    # 连接到 LiveKit 房间
            │
            ├─> setup_track_subscription()  # 订阅视频轨道
            │       │
            │       └─> on_track_subscribed()
            │               │
            │               └─> process_video_track()  # 持续更新帧
            │                       │
            │                       └─> frame_manager.update_frame()
            │
            └─> 进入对话循环
```

### 阶段 3: 用户对话处理 (核心流程)

```
用户说话 (Audio)
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│                    AgentSession Pipeline                        │
│                                                                 │
│   [Audio] ──> [STT] ──> [Text] ──> [VisionAgent.llm_node]      │
│                                           │                     │
│                                           ▼                     │
│                               ┌─────────────────────────┐       │
│                               │    llm_node() 核心流程   │       │
│                               │                         │       │
│                               │  1. 提取用户文本        │       │
│                               │  2. 开始延迟统计        │       │
│                               │  3. 调用 getChatPrompt  │──────────> Chat API
│                               │     获取动态 prompt     │       │
│                               │  4. 更新 system prompt  │       │
│                               │  5. 添加视频帧到消息    │──────────> VideoFrameManager
│                               │  6. 调用 LLM 推理       │       │
│                               │  7. 流式输出 tokens     │       │
│                               └─────────────────────────┘       │
│                                           │                     │
│                                           ▼                     │
│   [LLM Response] ──> [TTS] ──> [Audio] ──> 用户                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 阶段 4: 对话完成后处理

```
LLM 响应完成
    │
    ▼
conversation_item_added 事件触发
    │
    ├─> 获取完整响应文本
    │
    ├─> 并行分析视频帧
    │       │
    │       ├─> analyze_screen(screen_frame)  ──> Vision API
    │       └─> analyze_screen(camera_frame)  ──> Vision API
    │
    └─> save_gpt_result()                     ──> Chat API
            │
            └─> 保存对话记录 + 视频分析结果
```

## 🔌 Provider 工厂模式

### 支持的服务提供商

| 组件 | 提供商 | 插件 |
|------|--------|------|
| **LLM** | OpenAI | `livekit.plugins.openai` |
| | Google Gemini | `livekit.plugins.google` |
| | Gemini via OpenAI | `livekit.plugins.openai` (兼容模式) |
| | Grok | `livekit.plugins.openai` (兼容模式) |
| | 阿里云 Qwen | `livekit.plugins.aliyun` |
| **TTS** | MiniMax | `livekit.plugins.minimax_tts` (本地) |
| | ElevenLabs | `livekit.plugins.elevenlabs` |
| | 阿里云 CosyVoice | `livekit.plugins.aliyun` |
| **STT** | OpenAI Whisper | `livekit.plugins.openai` |
| | 阿里云 Paraformer | `livekit.plugins.aliyun` |

### 配置切换 (通过环境变量)

```bash
# LLM 提供商
LLM_PROVIDER=gemini_via_openai   # openai / google_gemini / grok / aliyun
LLM_MODEL=gemini-3-pro-preview

# TTS 提供商
TTS_PROVIDER=minimax              # minimax / elevenlabs / aliyun
TTS_DEFAULT_VOICE_ID=xxx

# STT 提供商
STT_PROVIDER=openai               # openai / aliyun
STT_MODEL=gpt-4o-mini-transcribe
```

## 📹 视频处理流程

```
LiveKit Room
    │
    ├─> TrackPublication (camera)
    │       │
    │       └─> process_video_track()
    │               │
    │               └─> VideoStream 循环读取帧
    │                       │
    │                       └─> frame_manager.update_frame("camera", frame)
    │
    └─> TrackPublication (screen_share)
            │
            └─> process_video_track()
                    │
                    └─> VideoStream 循环读取帧
                            │
                            └─> frame_manager.update_frame("screen_share", frame)


VisionAgent.llm_node() 调用时:
    │
    └─> _add_video_frames_to_message()
            │
            ├─> frame_manager.get_active_frames()
            │
            └─> 转换为 ImageContent 添加到用户消息
                    │
                    └─> LLM (Gemini/Qwen-VL) 进行多模态理解
```

## 📊 延迟统计点

```
时间线:
────────────────────────────────────────────────────────────────────>

[用户开始说话]
        │
        └─> start_turn()                     # T0: 开始计时
                │
                └─> [STT 处理]
                        │
                        └─> [API 调用: getChatPrompt]
                                │
                                └─> record_api_latency()  # T1: API 延迟
                                        │
                                        └─> [LLM 推理开始]
                                                │
                                                └─> record_llm_first_token()  # T2: 首 Token
                                                        │
                                                        └─> [LLM 推理完成]
                                                                │
                                                                └─> record_llm_complete()  # T3: LLM 完成
                                                                        │
                                                                        └─> [TTS 开始播放]
                                                                                │
                                                                                └─> record_tts_started()  # T4: 语音开始

延迟指标:
- API 延迟: T1 - T0
- LLM TTFT (Time to First Token): T2 - T0
- LLM 总延迟: T3 - T0
- 端到端延迟: T4 - T0
```

## 🔑 关键数据流

```
房间名称: "{userId}_{avatarId}_{timestamp}"
         │
         └─> RoomNameParser.parse()
                 │
                 └─> UserContext(user_id, avatar_id, session_id)
                         │
                         ├─> UserAPIClient.get_avatar_voice_info()
                         │       │
                         │       └─> voice_id (用于 TTS)
                         │
                         └─> ChatAPIClient.get_dynamic_prompt()
                                 │
                                 └─> PromptResponse
                                         │
                                         ├─> system_prompt (注入到 LLM)
                                         └─> pingback (用于后续保存)
```

这就是整个项目的工作流和模块调用关系！
