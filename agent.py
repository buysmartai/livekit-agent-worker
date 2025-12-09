"""
LiveKit Agent Worker - 阿里云语音助手服务

该服务集成了阿里云的 AI 能力：
- STT (语音识别): Paraformer 实时语音识别
- TTS (语音合成): CosyVoice 文本转语音
- LLM (大语言模型): Qwen 系列模型（支持多模态视觉分析）

环境变量要求:
- DASHSCOPE_API_KEY: 阿里云 DashScope API 密钥
- LIVEKIT_URL: LiveKit 服务器地址（可选）
- LIVEKIT_API_KEY: LiveKit API 密钥（可选）
- LIVEKIT_API_SECRET: LiveKit API 密钥（可选）
"""

import asyncio
import io
import logging
import time
from dotenv import load_dotenv
import os
from typing import Optional, AsyncIterable, Any
import json
from datetime import datetime
from livekit.plugins.minimax_tts import TTS as MiniMaxTTS

# HTTP 客户端 - 用于调用 REST API
try:
    import httpx
except ImportError:
    httpx = None
    logging.warning("⚠️  httpx 未安装，REST API 功能将不可用。安装: pip install httpx")

from livekit import rtc
from livekit.agents import (
    JobContext,
    WorkerOptions,
    cli,
    llm,
    ConversationItemAddedEvent,
)
from livekit.agents.voice import Agent, AgentSession, VoiceActivityVideoSampler, ModelSettings
from livekit.agents.utils import images
from livekit.plugins import aliyun, google, openai

# 尝试导入 update_instructions 函数（用于直接修改 chat_ctx）
try:
    from livekit.agents.voice.generation import update_instructions as sdk_update_instructions
    HAS_SDK_UPDATE_INSTRUCTIONS = True
except ImportError:
    HAS_SDK_UPDATE_INSTRUCTIONS = False
    logging.warning("⚠️  无法导入 sdk_update_instructions，将使用手动方式更新 chat_ctx")

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


class VisionAgent(Agent):
    """
    支持视觉分析的自定义 Agent

    功能特性：
    - 视频多模态分析
    - 动态调整 instructions
    - RAG 记忆增强
    - 动态 prompt 注入
    - 多轨道视频支持（摄像头 + 屏幕分享）
    - 从房间名称解析用户信息（格式：{userId}_{avatarId}_{timestamp}）
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        logger.info("🚀 VisionAgent 实例正在初始化...")

        # ========== 用户信息（从房间名称解析） ==========
        self._user_id: str = "default_user"
        self._avatar_id: str = "default_avatar"
        self._session_id: str = "default_session"  # 使用时间戳作为 session_id
        self._room_name: str = ""

        # 支持多个视频轨道
        self._video_frames: dict[str, rtc.VideoFrame | None] = {
            "camera": None,  # 摄像头轨道的最新帧
            "screen_share": None  # 屏幕分享轨道的最新帧
        }
        self._video_tracks: dict[str, rtc.RemoteVideoTrack] = {}
        self._mode: str = "general"  # 当前模式：general, detail, guide 等

        # 控制哪些轨道的图片会被发送到 LLM 摄像头和屏幕分享都要
        self._active_video_sources: set[str] = {"camera", "screen_share"}
        # 向后兼容
        self._last_video_frame: rtc.VideoFrame | None = None
        self._video_track: rtc.RemoteVideoTrack | None = None

        # RAG 相关
        self._memory_store: dict[str, list[str]] = {}  # 简单的内存存储
        self._enable_rag: bool = False  # 是否启用 RAG（已禁用）

        # REST API 相关
        self._last_pingback: Optional[dict] = None  # 存储最后一次 API 调用的 pingback 数据
        self._http_client: Optional[httpx.AsyncClient] = None  # HTTP 客户端（复用连接）

        # 初始化 HTTP 客户端
        if httpx:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, connect=3.0),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
            )
            logger.info("✅ HTTP 客户端已初始化")

        # ========== 延迟统计相关变量 ==========
        self._latency_metrics: dict = {}  # 存储当前轮次的延迟数据
        self._llm_node_start_time: float = 0.0  # llm_node 开始时间
        self._api_latency_ms: float = 0.0  # getChatPrompt API 延迟
        self._llm_first_token_time: float = 0.0  # LLM 首 token 时间
        self._llm_complete_time: float = 0.0  # LLM 完成时间
        self._tts_start_time: float = 0.0  # TTS 开始播放时间
        self._current_turn_id: int = 0  # 当前对话轮次 ID

        logger.info(f"✅ VisionAgent 初始化完成！活跃视频源: {self._active_video_sources}")

    def _log_latency_metrics(self, stage: str = "complete", metrics_snapshot: dict = None) -> None:
        """
        输出格式化的延迟统计日志
        
        Args:
            stage: 统计阶段，可选 "llm_first_token", "llm_complete", "tts_started", "complete"
            metrics_snapshot: 可选的 metrics 快照（用于 TTS 事件，避免被新轮次覆盖）
        """
        # 使用传入的快照或当前 metrics
        metrics = metrics_snapshot if metrics_snapshot else self._latency_metrics
        
        # 获取该轮次的开始时间（从 metrics 中获取，而不是实例变量）
        start_time = metrics.get("llm_node_start_time", 0)
        if start_time == 0:
            return
        
        # 计算各阶段延迟
        api_latency = metrics.get("api_latency_ms", 0)
        
        llm_ttft = 0.0
        if metrics.get("llm_first_token_time"):
            llm_ttft = (metrics["llm_first_token_time"] - start_time) * 1000
        
        llm_complete = 0.0
        if metrics.get("llm_complete_time"):
            llm_complete = (metrics["llm_complete_time"] - start_time) * 1000
        
        tts_start = 0.0
        total_latency = 0.0
        if metrics.get("tts_start_time"):
            tts_start = (metrics["tts_start_time"] - start_time) * 1000
            total_latency = tts_start
        elif llm_complete > 0:
            total_latency = llm_complete
        elif llm_ttft > 0:
            total_latency = llm_ttft
        
        # 计算 LLM 生成耗时（从首 token 到完成）
        llm_generation = 0.0
        if llm_complete > 0 and llm_ttft > 0:
            llm_generation = llm_complete - llm_ttft
        
        # 计算 TTS 启动延迟（从 LLM 完成到 TTS 开始）
        tts_startup = 0.0
        if tts_start > 0 and llm_complete > 0:
            tts_startup = tts_start - llm_complete
        
        # 输出日志
        turn_id = metrics.get("turn_id", self._current_turn_id)
        user_text = metrics.get("user_text", "")[:30]
        
        logger.info("")
        logger.info("=" * 70)
        logger.info(f"⏱️  [延迟统计] Turn #{turn_id} | Stage: {stage}")
        logger.info(f"📝 用户输入: {user_text}...")
        logger.info("-" * 70)
        logger.info(f"├─ 🌐 API (getChatPrompt):    {api_latency:>8.2f} ms")
        logger.info(f"├─ 🚀 LLM TTFT (首token):     {llm_ttft:>8.2f} ms")
        logger.info(f"├─ 📝 LLM 生成耗时:           {llm_generation:>8.2f} ms")
        logger.info(f"├─ ✅ LLM 完成 (从开始):      {llm_complete:>8.2f} ms")
        logger.info(f"├─ 🔊 TTS 启动延迟:           {tts_startup:>8.2f} ms")
        logger.info(f"├─ 🎵 TTS 开始播放 (从开始):  {tts_start:>8.2f} ms")
        logger.info("-" * 70)
        logger.info(f"└─ 📊 总延迟 (用户输入→TTS):  {total_latency:>8.2f} ms")
        logger.info("=" * 70)
        logger.info("")

    def _reset_latency_metrics(self) -> None:
        """重置延迟统计数据（新轮次开始时调用）"""
        self._current_turn_id += 1
        self._llm_node_start_time = time.perf_counter()
        self._latency_metrics = {
            "turn_id": self._current_turn_id,
            "llm_node_start_time": self._llm_node_start_time,
            "api_latency_ms": 0.0,
            "llm_first_token_time": 0.0,
            "llm_complete_time": 0.0,
            "tts_start_time": 0.0,
            "user_text": "",
        }

    def record_tts_started(self) -> None:
        """记录 TTS 开始播放时间（由外部事件调用）"""
        tts_time = time.perf_counter()
        
        # 更新当前 metrics（如果还是同一轮次）
        self._tts_start_time = tts_time
        self._latency_metrics["tts_start_time"] = tts_time
        
        # 创建 metrics 快照用于日志输出（避免被新轮次覆盖）
        metrics_snapshot = self._latency_metrics.copy()
        
        # TTS 开始时输出完整统计（使用快照）
        self._log_latency_metrics("tts_started", metrics_snapshot)

    def set_user_info_from_room_name(self, room_name: str) -> bool:
        """
        从房间名称解析用户信息
        
        房间名称格式: {userId}_{avatarId}_{timestamp}
        例如: abc123_def456_1701590400
        
        Args:
            room_name: 房间名称
            
        Returns:
            是否解析成功
        """
        self._room_name = room_name
        
        if not room_name:
            logger.warning("⚠️  房间名称为空，使用默认用户信息")
            return False
        
        try:
            parts = room_name.split('_')
            
            if len(parts) >= 3:
                # 格式: userId_avatarId_timestamp
                self._user_id = parts[0]
                self._avatar_id = parts[1]
                # 时间戳部分可能包含额外信息，取第三部分作为 session_id
                self._session_id = '_'.join(parts[2:])  # 支持时间戳后面可能有其他内容
                
                logger.info(f"✅ 从房间名称解析用户信息成功:")
                logger.info(f"   📛 房间名称: {room_name}")
                logger.info(f"   👤 user_id: {self._user_id}")
                logger.info(f"   🎭 avatar_id: {self._avatar_id}")
                logger.info(f"   🔑 session_id: {self._session_id}")
                return True
            elif len(parts) == 2:
                # 兼容格式: userId_avatarId（没有时间戳）
                self._user_id = parts[0]
                self._avatar_id = parts[1]
                self._session_id = str(int(datetime.now().timestamp()))
                
                logger.warning(f"⚠️  房间名称只有2段，自动生成 session_id:")
                logger.info(f"   👤 user_id: {self._user_id}")
                logger.info(f"   🎭 avatar_id: {self._avatar_id}")
                logger.info(f"   🔑 session_id: {self._session_id} (自动生成)")
                return True
            else:
                # 无法解析，使用房间名称作为 session_id
                logger.warning(f"⚠️  无法解析房间名称 '{room_name}'，格式不符合 userId_avatarId_timestamp")
                self._session_id = room_name
                return False
                
        except Exception as e:
            logger.error(f"❌ 解析房间名称异常: {e}")
            return False

    def get_user_context(self) -> dict:
        """
        获取用户上下文信息
        
        Returns:
            包含 user_id, avatar_id, session_id, timezone 的字典
        """
        return {
            "user_id": self._user_id,
            "avatar_id": self._avatar_id,
            "session_id": self._session_id,
            "timezone": os.getenv("TIMEZONE", "Asia/Shanghai"),
            "room_name": self._room_name
        }

    def _manual_update_chat_ctx_system(self, chat_ctx: llm.ChatContext, system_text: str) -> None:
        """
        手动更新 chat_ctx 中的 system message
        
        当 SDK 的 update_instructions 函数不可用时使用此方法
        
        Args:
            chat_ctx: 对话上下文
            system_text: 新的 system prompt 文本
        """
        # 查找并替换现有的 system message
        found_system = False
        for i, item in enumerate(chat_ctx.items):
            if isinstance(item, llm.ChatMessage) and item.role == "system":
                # 直接修改 content
                item.content = [system_text]
                found_system = True
                logger.info(f"✅ 已手动更新 chat_ctx 中的 system message (index={i})")
                break
        
        # 如果没有找到 system message，在开头插入一个新的
        if not found_system:
            new_system_msg = llm.ChatMessage(
                role="system",
                content=[system_text]
            )
            chat_ctx.items.insert(0, new_system_msg)
            logger.info("✅ 已在 chat_ctx 开头插入新的 system message")

    def set_active_video_sources(self, sources: list[str]) -> None:
        """
        设置哪些视频源应该被发送到 LLM

        Args:
            sources: 视频源列表，可选值: ["camera", "screen_share"]
                    - ["camera"]: 只发送摄像头画面
                    - ["screen_share"]: 只发送屏幕分享画面
                    - ["camera", "screen_share"]: 同时发送两个画面
        """
        self._active_video_sources = set(sources)
        logger.info(f"已设置活跃视频源: {sources}")

    def update_video_frame(self, source_type: str, frame: rtc.VideoFrame) -> None:
        """
        更新指定来源的视频帧

        Args:
            source_type: 视频源类型 ("camera" 或 "screen_share")
            frame: 视频帧
        """
        self._video_frames[source_type] = frame
        # logger.debug(f"🖼️  更新 {source_type} 视频帧: {frame.width}x{frame.height}")

        # 向后兼容：更新 _last_video_frame 为摄像头帧
        if source_type == "camera":
            self._last_video_frame = frame

    def set_mode(self, mode: str, video_sources: list[str] | None = None) -> None:
        """
        设置 Agent 的工作模式，并可选地调整活跃视频源

        Args:
            mode: 模式名称，例如 "general", "screen_analysis", "dual_view" 等
            video_sources: 可选，该模式下使用的视频源列表

        示例:
            # 一般对话模式，只使用摄像头
            agent.set_mode("general", ["camera"])

            # 屏幕分析模式，只使用屏幕分享
            agent.set_mode("screen_analysis", ["screen_share"])

            # 双视图模式，同时使用摄像头和屏幕
            agent.set_mode("dual_view", ["camera", "screen_share"])
        """
        self._mode = mode
        if video_sources is not None:
            self.set_active_video_sources(video_sources)
        logger.info(f"Agent 模式已设置为: {mode}, 活跃视频源: {self._active_video_sources}")

    async def get_dynamic_prompt(
            self,
            user_text: str,
            user_id: str = "default_user",
            avatar_id: str = "default_avatar",
            session_id: str = "default_session"
    ) -> Optional[dict]:
        """
        调用后端 REST API 获取动态 prompt

        Args:
            user_text: 用户输入的文本
            user_id: 用户 ID
            avatar_id: 角色 ID
            session_id: 会话 ID

        Returns:
            包含 data (messages, maxOutputTokens 等) 和 pingback 的字典，如果失败返回 None
        """
        import time
        start_time = time.perf_counter()
        
        if not self._http_client:
            logger.error("❌ HTTP 客户端未初始化，无法调用 REST API")
            return None

        # 从环境变量获取 API 配置
        api_base_url = os.getenv("CHAT_API_BASE_URL", "https://your-api.com")
        api_key = os.getenv("CHAT_API_KEY", "")

        try:
            # 构建请求体（参考你提供的 API 格式）
            request_body = {
                "reqId": os.urandom(16).hex(),
                "timezone": os.getenv("TIMEZONE", "Asia/Shanghai"),
                "appOs": "livekit",
                "appVersion": "1.0.0",
                "userLocalTime": datetime.now().isoformat(),
                "userId": user_id,
                "avatarId": avatar_id,
                "chatStatusType": "append",
                "sessionId": session_id,
                "agentContext": {
                    "agentType": "voice_chat",
                    "context": {}
                },
                "language": os.getenv("LANGUAGE", "en"),
                "input": None,
                "latestUserInput": [
                    {
                        "source": "content",
                        "type": "text",
                        "text": user_text,
                        "image_url": None,
                        "input_audio": None
                    }
                ],
                "timestamp": int(datetime.now().timestamp() * 1000),
                "modelProvider": os.getenv("MODEL_PROVIDER", "vercel"),
                "gptModel": os.getenv("GPT_MODEL", "claude-3-7-sonnet-20250219")
            }

            logger.info(f"🌐 调用 getChatPrompt API: {api_base_url}/chat/getChatPrompt")
            logger.info(f"📋 请求参数: userId={user_id}, avatarId={avatar_id}, sessionId={session_id}")

            response = await self._http_client.post(
                f"{api_base_url}/chat/getChatPrompt",
                json=request_body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
            )
            
            elapsed_time = (time.perf_counter() - start_time) * 1000  # 转换为毫秒
            logger.info(f"⏱️  getChatPrompt API 耗时: {elapsed_time:.2f}ms")
            
            # 记录 API 延迟到统计数据
            self._latency_metrics["api_latency_ms"] = elapsed_time

            if response.status_code == 200:
                result = response.json()
                if result.get("code") == "0":
                    logger.info(f"✅ 获取动态 prompt 成功 (总耗时: {elapsed_time:.2f}ms)")

                    # 返回完整的响应数据
                    return {
                        "data": result.get("data", {}),
                        "pingback": result.get("pingback", {}),
                        "messages": result.get("messages", [])
                    }
                else:
                    logger.warning(f"⚠️  API 返回错误码: {result.get('code')} (耗时: {elapsed_time:.2f}ms)")
                    return None
            else:
                logger.error(f"❌ API 请求失败: HTTP {response.status_code} (耗时: {elapsed_time:.2f}ms)")
                logger.error(f"响应内容: {response.text[:200]}")
                return None

        except httpx.TimeoutException:
            elapsed_time = (time.perf_counter() - start_time) * 1000
            logger.error(f"❌ getChatPrompt API 超时（耗时: {elapsed_time:.2f}ms，超过10秒）")
            return None
        except Exception as e:
            elapsed_time = (time.perf_counter() - start_time) * 1000
            logger.error(f"❌ getChatPrompt API 调用异常 (耗时: {elapsed_time:.2f}ms): {e}", exc_info=True)
            return None

    async def get_avatar_voice_info(self, avatar_id: str, user_id: str = "default_user") -> Optional[dict]:
        """
        调用后端 REST API 获取 Avatar 的语音配置信息

        Args:
            avatar_id: Avatar ID
            user_id: 用户 ID

        Returns:
            包含 voiceInfo 的字典，如果失败返回 None
            返回结构:
            {
                "voiceApiId": "string",      # MiniMax 声音 ID，用于 TTS
                "audioUrl": "string",         # 声音预览音频 URL
                "description": "string",      # 声音描述
                "tags": "string",             # 标签
                "elevenlabApiId": "string"    # ElevenLabs 声音 ID（可选）
            }
        """
        import time
        start_time = time.perf_counter()

        if not self._http_client:
            logger.error("❌ HTTP 客户端未初始化，无法调用 REST API")
            return None

        # 从环境变量获取 API 配置
        api_base_url = os.getenv("CHAT_API_BASE_URL", "https://your-api.com")
        api_key = os.getenv("CHAT_API_KEY", "")

        try:
            # 构建请求体
            request_body = {
                "userId": user_id,
                "requestId": os.urandom(16).hex(),
                "timezone": os.getenv("TIMEZONE", "Asia/Shanghai"),
                "userLocalTime": datetime.now().isoformat(),
                "avatarId": avatar_id,
            }

            logger.info(f"🌐 调用 queryUserAvatarById API: {api_base_url}/user/queryUserAvatarById")
            logger.info(f"📋 请求参数: userId={user_id}, avatarId={avatar_id}")

            response = await self._http_client.post(
                f"{api_base_url}/user/queryUserAvatarById",
                json=request_body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
            )

            elapsed_time = (time.perf_counter() - start_time) * 1000  # 转换为毫秒
            logger.info(f"⏱️  queryUserAvatarById API 耗时: {elapsed_time:.2f}ms")

            if response.status_code == 200:
                result = response.json()
                if result.get("code") == "0" or result.get("code") == 0:
                    data = result.get("data", {})
                    voice_info = data.get("voiceInfo", {})
                    if voice_info:
                        logger.info(f"✅ 获取 Avatar 语音信息成功:")
                        logger.info(f"   🎤 voiceApiId: {voice_info.get('voiceApiId', 'N/A')}")
                        logger.info(f"   🔊 description: {voice_info.get('description', 'N/A')}")
                        return voice_info
                    else:
                        logger.warning(f"⚠️  Avatar {avatar_id} 没有配置 voiceInfo")
                        return None
                else:
                    logger.warning(f"⚠️  API 返回错误码: {result.get('code')} (耗时: {elapsed_time:.2f}ms)")
                    return None
            else:
                logger.error(f"❌ API 请求失败: HTTP {response.status_code} (耗时: {elapsed_time:.2f}ms)")
                logger.error(f"响应内容: {response.text[:200]}")
                return None

        except httpx.TimeoutException:
            elapsed_time = (time.perf_counter() - start_time) * 1000
            logger.error(f"❌ queryUserAvatarById API 超时（耗时: {elapsed_time:.2f}ms，超过10秒）")
            return None
        except Exception as e:
            elapsed_time = (time.perf_counter() - start_time) * 1000
            logger.error(f"❌ queryUserAvatarById API 调用异常 (耗时: {elapsed_time:.2f}ms): {e}", exc_info=True)
            return None

    async def analyze_screen(self, frame: rtc.VideoFrame, user_input: str = "") -> Optional[str]:
        """
        使用多模态大模型分析屏幕内容
        
        支持 OpenAI 兼容 API（如 grok-4-fast-non-reasoning）

        Args:
            frame: 视频帧
            user_input: 用户的问题（用于生成针对性的提取 prompt）

        Returns:
            提取的文本/描述内容，如果失败返回 None
        """
        try:
            import base64

            # 从环境变量获取 API 配置
            base_url = os.getenv("SCREEN_ANALYSIS_API_BASE_URL", "https://147ai.com/v1/")
            api_key = os.getenv("SCREEN_ANALYSIS_API_KEY", "sk-2KCuGeqtkfreSLIjZHASZBcwYJdZehOqfjuZEemZVsc3jHiy")
            model = os.getenv("SCREEN_ANALYSIS_MODEL", "grok-4-fast-non-reasoning")

            if not api_key:
                logger.error("❌ [ScreenAnalysis] API_KEY 未配置")
                return None

            if not self._http_client:
                logger.error("❌ [ScreenAnalysis] HTTP 客户端未初始化")
                return None

            # 使用 LiveKit 官方 API 将 VideoFrame 转换为 JPEG bytes
            logger.info(f"🔄 [ScreenAnalysis] 转换视频帧: {frame.width}x{frame.height}, type={frame.type}")

            encode_options = images.EncodeOptions(
                format="JPEG",
                quality=85,
                resize_options=images.ResizeOptions(
                    width=1024,
                    height=1024,
                    strategy="scale_aspect_fit"
                )
            )
            jpeg_bytes = images.encode(frame, encode_options)

            # 将图片转换为 base64
            image_base64 = base64.b64encode(jpeg_bytes).decode('utf-8')

            # 构建 prompt
            if not user_input:
                user_input = getattr(self, '_last_user_input', 'what is on the screen')
            
            prompt = (
                f'The user is sharing their screen with you and asked "{user_input}".\n'
                "Extract only the on-screen information that may help answer this question.\n"
                "Do NOT provide an answer or recommendation.\n"
                "Output only the extracted information, within 1000 words."
            )

            logger.info(f"🔍 [ScreenAnalysis] 开始分析屏幕内容 (model={model})...")

            # 构建 OpenAI 兼容的请求
            request_body = {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_base64}"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 1500
            }

            # 确保 base_url 以 / 结尾
            if not base_url.endswith('/'):
                base_url += '/'

            # 发送请求
            response = await self._http_client.post(
                f"{base_url}chat/completions",
                json=request_body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                timeout=30.0  # 图片分析可能需要更长时间
            )

            if response.status_code == 200:
                result = response.json()
                # 提取响应内容
                if result.get("choices") and len(result["choices"]) > 0:
                    result_text = result["choices"][0].get("message", {}).get("content", "")
                    if result_text:
                        logger.info(f"✅ [ScreenAnalysis] 分析完成 (前100字): {result_text[:100]}...")
                        return result_text
                    else:
                        logger.warning("⚠️  [ScreenAnalysis] 返回内容为空")
                        return None
                else:
                    logger.warning("⚠️  [ScreenAnalysis] 未返回有效的 choices")
                    return None
            else:
                logger.error(f"❌ [ScreenAnalysis] API 请求失败: HTTP {response.status_code}")
                logger.error(f"响应内容: {response.text[:200]}")
                return None

        except Exception as e:
            logger.error(f"❌ [ScreenAnalysis] 分析失败: {e}", exc_info=True)
            return None

    async def save_gpt_result(
            self,
            gpt_result: str,
            pingback: dict,
            user_context: Optional[dict] = None,
            screen_frame_text: Optional[str] = None,
            camera_frame_text: Optional[str] = None
    ) -> bool:
        """
        调用后端 REST API 保存 GPT 生成的结果（并行处理，不阻塞主流程）

        Args:
            gpt_result: LLM 生成的文本（Agent 对用户的回复）
            pingback: getChatPrompt 返回的 pingback 数据
            user_context: 用户上下文（包含 userId, avatarId, sessionId, timezone）
            screen_frame_text: 屏幕分享帧的分析内容
            camera_frame_text: 摄像头帧的分析内容

        Returns:
            是否保存成功
        """
        if not self._http_client:
            logger.error("❌ [并行] HTTP 客户端未初始化")
            return False

        if not pingback:
            logger.warning("⚠️  [并行] 没有 pingback 数据，跳过 saveGptResult")
            return False

        api_base_url = os.getenv("CHAT_API_BASE_URL", "")
        api_key = os.getenv("CHAT_API_KEY", "")
        
        # 使用传入的 user_context，如果没有则从环境变量获取
        ctx = user_context or {}
        user_id = ctx.get("user_id", os.getenv("USER_ID", "default_user"))
        avatar_id = ctx.get("avatar_id", os.getenv("AVATAR_ID", "default_avatar"))
        session_id = ctx.get("session_id", os.getenv("SESSION_ID", "default_session"))
        timezone = ctx.get("timezone", os.getenv("TIMEZONE", "Asia/Shanghai"))

        try:
            request_body = {
                "reqId": os.urandom(16).hex(),
                "timezone": timezone,
                "appOs": "livekit",
                "appVersion": "1.0.0",
                "userLocalTime": datetime.now().isoformat(),
                "userId": user_id,
                "avatarId": avatar_id,
                "agentType": "voice_chat",
                "chatStatusType": None,
                "sessionId": session_id,
                "agentContext": None,
                "timestamp": int(datetime.now().timestamp() * 1000),
                "gptResult": gpt_result,
                "networkResult": None,
                "screenFrameText": screen_frame_text,
                "cameraFrameText": camera_frame_text,
                "imgPay": "N",
                "isVipImg": "N",
                "pingback": pingback
            }

            logger.info(f"💾 [并行] 调用 saveGptResult API...")
            logger.info(f"   GPT Result (前150字): {gpt_result[:150]}...")
            if screen_frame_text:
                logger.info(f"   Screen Text (前150字): {screen_frame_text[:150]}...")
            if camera_frame_text:
                logger.info(f"   Camera Text (前150字): {camera_frame_text[:150]}...")

            response = await self._http_client.post(
                f"{api_base_url}/chat/saveGptResult",
                json=request_body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                timeout=5.0
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("code") == "0":
                    logger.info(f"✅ [并行] saveGptResult 成功")
                    return True
                else:
                    logger.warning(f"⚠️  [并行] 返回错误码: {result.get('code')}")
                    return False
            else:
                logger.error(f"❌ [并行] HTTP {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"❌ [并行] saveGptResult 异常: {e}")
            return False

    async def llm_node(
            self,
            chat_ctx: llm.ChatContext,
            tools: list[llm.FunctionTool],
            model_settings: ModelSettings,
    ) -> AsyncIterable[llm.ChatChunk | str]:
        """
        LLM 节点 - 拦截所有用户输入（语音 + 文字）

        这是 Agent pipeline 中处理 LLM 推理的核心节点。
        无论用户是通过语音还是文字输入，都会经过这个方法。

        功能：
        1. 调用 REST API 获取动态 prompt
        2. 动态更新 system instructions
        3. 添加视频帧到用户消息
        4. 启动后台视频记忆处理任务
        5. 调用默认的 LLM 处理

        Args:
            chat_ctx: 对话上下文，包含所有历史消息
            tools: 可用的工具列表
            model_settings: 模型设置

        Yields:
            LLM 生成的内容块
        """
        logger.info("=" * 80)
        logger.info("🔔 VisionAgent.llm_node 被调用！（拦截所有用户输入）")
        logger.info("=" * 80)

        # ========== 0. 初始化延迟统计 ==========
        self._reset_latency_metrics()
        logger.info(f"⏱️  [延迟统计] Turn #{self._current_turn_id} 开始计时")

        # ========== 1. 查找最新的用户消息 ==========
        user_message: llm.ChatMessage | None = None
        for item in reversed(chat_ctx.items):
            if isinstance(item, llm.ChatMessage) and item.role == "user":
                user_message = item
                break

        if not user_message:
            logger.warning("⚠️  未找到用户消息，直接调用默认 LLM")
            async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
                yield chunk
            return

        user_text = user_message.text_content or ""
        logger.info(f"📝 用户输入: {user_text}")
        
        # 记录用户输入文本（用于延迟统计日志）
        self._latency_metrics["user_text"] = user_text

        # 从实例变量获取用户上下文（已从房间名称解析）
        user_context = self.get_user_context()
        user_id = user_context["user_id"]
        avatar_id = user_context["avatar_id"]
        session_id = user_context["session_id"]
        timezone = user_context["timezone"]
        
        logger.info(f"👤 用户上下文: user_id={user_id}, avatar_id={avatar_id}, session_id={session_id}")

        pingback: dict | None = None

        # ========== 2. 调用 REST API 获取动态 prompt ==========
        if self._http_client:
            logger.info(f"🔄 准备调用 getChatPrompt API...")

            prompt_result = await self.get_dynamic_prompt(
                user_text=user_text,
                user_id=user_id,
                avatar_id=avatar_id,
                session_id=session_id
            )

            if prompt_result:
                logger.info(f"📥 prompt_result: {json.dumps(prompt_result, ensure_ascii=False)[:500]}...")

                # 获取返回的数据
                data = prompt_result.get("data", {})
                pingback = prompt_result.get("pingback", {})
                api_messages = data.get("messages", [])

                # 保存 pingback 数据（也存一份到实例变量，用于兼容）
                self._last_pingback = pingback
                prompt_id = pingback.get("promptId", "N/A")
                logger.info(f"💾 保存 pingback 数据，promptId={prompt_id}")

                # 处理返回的 messages，动态更新 system prompt
                if api_messages:
                    logger.info(f"📋 API 返回了 {len(api_messages)} 条消息")

                    for api_msg in api_messages:
                        role = api_msg.get("role")
                        content = api_msg.get("content")

                        if role == "system" and content:
                            # 提取 system message 的文本
                            system_text = ""
                            if isinstance(content, str):
                                system_text = content
                            elif isinstance(content, list):
                                # 处理列表格式的 content
                                text_parts = []
                                for item in content:
                                    if isinstance(item, dict) and item.get("type") == "text":
                                        text_parts.append(item.get("text", ""))
                                system_text = " ".join(text_parts)

                            if system_text:
                                logger.info(f"🎭 动态更新 system prompt (前100字): {system_text[:100]}...")

                                # ===== 关键修复：直接修改当前 chat_ctx 的 system message =====
                                # self.update_instructions() 只会影响后续轮次，不会影响当前 chat_ctx
                                # 所以需要直接修改传入的 chat_ctx
                                
                                if HAS_SDK_UPDATE_INSTRUCTIONS:
                                    # 方法1: 使用 SDK 提供的函数
                                    try:
                                        sdk_update_instructions(chat_ctx, instructions=system_text, add_if_missing=True)
                                        logger.info("✅ 已通过 SDK 函数更新 chat_ctx 的 system prompt")
                                    except Exception as e:
                                        logger.warning(f"⚠️  SDK update_instructions 失败: {e}，尝试手动更新")
                                        self._manual_update_chat_ctx_system(chat_ctx, system_text)
                                else:
                                    # 方法2: 手动遍历并修改 chat_ctx.items
                                    self._manual_update_chat_ctx_system(chat_ctx, system_text)
                                
                                # 同时更新 Agent 内部状态（影响后续轮次）
                                await self.update_instructions(system_text)
                                logger.info("✅ System prompt 已动态更新（当前轮次 + 后续轮次）")

                # ========== 添加预填充 Assistant 消息，跳过 Gemini 3 思考链 ==========
                # Gemini 3 Pro 无法完全禁用思考功能，通过预填充 assistant 消息
                # 告诉模型"思考已完成"，绕过内置思考链，减少延迟
                thinking_done_msg = llm.ChatMessage(
                    role="assistant",
                    content=["""<think>  
    内部隐性推理链已完成。所有必要判断、路径选择与上下文分析均已结束。  
    本阶段标记为"结束"，不再继续展开。  
</think>"""]
                )
                chat_ctx.items.append(thinking_done_msg)
                logger.info("🧠 已添加预填充 Assistant 消息（跳过思考链）")

                # 可选：记录其他配置信息
                max_tokens = data.get("maxOutputTokens", "N/A")
                temperature = data.get("temperature", "N/A")
                logger.info(f"⚙️  LLM 配置: maxOutputTokens={max_tokens}, temperature={temperature}")
            else:
                logger.warning("⚠️  未能获取动态 prompt，使用默认配置")

        # ========== 3. 视觉增强：添加活跃视频源的帧到用户消息 ==========
        image_contents = []
        logger.info(f"🎥 活跃视频源: {self._active_video_sources}")

        # 用于后台任务的视频帧快照
        video_frame_for_memory: rtc.VideoFrame | None = None
        video_source_for_memory: str = ""

        for source_type in self._active_video_sources:
            frame = self._video_frames.get(source_type)
            if frame is not None:
                logger.info(
                    f"✅ {source_type} 视频帧已捕获: {frame.width}x{frame.height}"
                )

                # 保存用于后台任务的视频帧（优先屏幕分享）
                if source_type == "screen_share" or not video_frame_for_memory:
                    video_frame_for_memory = frame
                    video_source_for_memory = source_type

                # 创建 ImageContent 并添加描述
                image_content = llm.ImageContent(
                    image=frame,
                    inference_width=512,
                    inference_height=512,
                )
                image_contents.append((source_type, image_content))

                logger.info(
                    f"🖼️  {source_type} ImageContent 创建成功，"
                    f"将以 512x512 分辨率发送到 LLM"
                )
            else:
                logger.warning(
                    f"⚠️  {source_type} 视频帧未捕获（frame=None）"
                )

        # 将图像添加到用户消息内容中
        if image_contents:
            logger.info(f"📸 准备将 {len(image_contents)} 个视频源的图像添加到消息")

            # 如果有多个图像源，在文本中添加说明
            if len(image_contents) > 1:
                source_description = "（包含 " + "、".join([s for s, _ in image_contents]) + " 的画面）"
                if isinstance(user_message.content, str):
                    user_message.content = [user_message.content + source_description]
                elif isinstance(user_message.content, list):
                    # 修改第一个文本内容
                    for i, c in enumerate(user_message.content):
                        if isinstance(c, str):
                            user_message.content[i] = c + source_description
                            break

            # 转换为列表格式
            if isinstance(user_message.content, str):
                user_message.content = [user_message.content]
            elif not isinstance(user_message.content, list):
                user_message.content = []

            # 添加所有图像内容
            for source_type, image_content in image_contents:
                # 检查是否已经添加了该源的图片（避免重复）
                has_image = any(
                    isinstance(c, llm.ImageContent) for c in user_message.content
                )
                if not has_image or len(image_contents) > 1:
                    user_message.content.append(image_content)
                    logger.info(f"✅ {source_type} 图像已添加到消息内容")

            logger.info(
                f"🚀 最终消息内容包含: {len([c for c in user_message.content if isinstance(c, str)])} 个文本, "
                f"{len([c for c in user_message.content if isinstance(c, llm.ImageContent)])} 个图像"
            )
        else:
            logger.warning("⚠️  没有可用的视频帧，仅发送文本内容")

        # ========== 4. 并行处理：保存视频记忆（不阻塞主流程）==========
        # 如果有 pingback 数据且有视频帧，启动后台任务保存记忆
        # 注意：传入快照数据，避免竞态条件
        # logger.info(f"🔔 检查是否启动视频记忆处理任务: has_video={video_frame_for_memory is not None}, has_pingback={pingback is not None}")
        # if pingback and video_frame_for_memory:
        #     # 创建后台任务，传入快照数据（不等待完成）
        #     asyncio.create_task(
        #         self.process_video_memory_async(
        #             pingback=pingback.copy(),  # 传入 pingback 的拷贝
        #             user_context=user_context.copy(),  # 传入用户上下文的拷贝
        #             video_frame=video_frame_for_memory,  # 传入视频帧快照
        #             video_source=video_source_for_memory
        #         )
        #     )
        #     logger.info("🚀 [并行] 已启动视频记忆处理任务（后台运行，不阻塞对话）")

        # ========== 5. 调用 LLM 并记录延迟 ==========
        is_first_token = True
        async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
            # 记录首 token 时间 (TTFT - Time To First Token)
            if is_first_token:
                self._llm_first_token_time = time.perf_counter()
                self._latency_metrics["llm_first_token_time"] = self._llm_first_token_time
                ttft_ms = (self._llm_first_token_time - self._llm_node_start_time) * 1000
                logger.info(f"⏱️  [延迟统计] LLM 首 Token (TTFT): {ttft_ms:.2f}ms")
                is_first_token = False
            yield chunk
        
        # LLM 完成时记录时间
        self._llm_complete_time = time.perf_counter()
        self._latency_metrics["llm_complete_time"] = self._llm_complete_time
        llm_total_ms = (self._llm_complete_time - self._llm_node_start_time) * 1000
        logger.info(f"⏱️  [延迟统计] LLM 完成: {llm_total_ms:.2f}ms")
        
        # 输出 LLM 完成阶段的统计（TTS 还未开始）
        self._log_latency_metrics("llm_complete")


async def entrypoint(ctx: JobContext):
    """
    Agent 入口函数
    
    当 LiveKit 房间创建或 Agent 被调用时，该函数会被执行。
    
    房间名称格式: {userId}_{avatarId}_{timestamp}
    例如: abc123_def456_1701590400
    """
    room_name = ctx.room.name
    logger.info("=" * 80)
    logger.info(f"🏠 连接到房间: {room_name}")
    logger.info("=" * 80)

    # 创建支持视觉分析的 Agent 实例
    # instructions 参数定义了助手的行为和角色
    agent = VisionAgent(
        instructions=""  # 动态从 API 获取，初始为空
    )
    
    # ========== 从房间名称解析用户信息 ==========
    # 房间名称格式: {userId}_{avatarId}_{timestamp}
    parse_success = agent.set_user_info_from_room_name(room_name)
    if not parse_success:
        logger.warning(f"⚠️  房间名称 '{room_name}' 解析失败，将使用默认用户信息")

    # ========== 动态获取 Avatar 语音配置 ==========
    # 默认 voice_id（当 API 调用失败时使用）
    default_voice_id = "moss_audio_23e7a6cf-0996-11f0-ab96-82dcc6ce9d69"
    voice_id = default_voice_id
    
    if agent._avatar_id:
        logger.info(f"🎤 正在获取 Avatar {agent._avatar_id} 的语音配置...")
        voice_info = await agent.get_avatar_voice_info(agent._avatar_id, agent._user_id)
        logger.info(f"📥 voice_info: {voice_info}")
        if voice_info and voice_info.get("voiceApiId"):
            voice_id = voice_info["voiceApiId"]
            logger.info(f"✅ 使用动态 voice_id: {voice_id}")
        else:
            logger.warning(f"⚠️  无法获取 Avatar 语音配置，使用默认 voice_id: {default_voice_id}")
    else:
        logger.warning(f"⚠️  未解析到 avatar_id，使用默认 voice_id: {default_voice_id}")

    # 创建 Agent 会话，配置语音和语言模型组件
    session = AgentSession(
        # 语音识别 (STT) - 使用 OpenAI STT
        stt=openai.STT(
            model="gpt-4o-mini-transcribe",  # OpenAI 默认推荐模型
            # language="zh",  # 中文语音识别
            use_realtime=True
        ),
        # ========== 原阿里云 STT 配置（已注释） ==========
        # stt=aliyun.STT(
        #     model="paraformer-realtime-v2",  # 实时语音识别模型
        #     # vocabulary_id="your_vocabulary_id",  # 可选：热词表 ID，提高特定词汇识别准确率
        # ),

        # 语音合成 (TTS) - 使用 MiniMax T2A 语音合成
        # voice_id 从后端 API 动态获取（基于 avatar_id）
        tts=MiniMaxTTS(
            model="speech-2.6-turbo",  # 快速模型，可选：speech-2.6-hd, speech-2.6-turbo
            voice_id=voice_id,  # 动态获取的 voice_id
            speed=1.0,  # 语速 (0.5-2.0)
            volume=1.0,
            pitch=0,
            # api_key="your_api_key",  # 或设置环境变量 MINIMAX_API_KEY
        ),
        # ========== 原 ElevenLabs TTS 配置（已注释） ==========
        # tts=elevenlabs.TTS(
        #     voice_id="tQ4MEZFJOzsahSEEZtHK",
        #     model="eleven_turbo_v2_5",
        #     voice_settings=VoiceSettings(
        #         stability=0.5,
        #         similarity_boost=0.75,
        #         speed=1.2,
        #         use_speaker_boost=True
        #     ),
        # ),

        # 大语言模型 (LLM) - 使用 Google Gemini 多模态模型
        # 参考: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/3-pro?hl=zh-cn
        # 原生 Google LLM（已注释）:
        # llm=google.LLM(
        #     model="gemini-2.5-flash",  # Gemini 3 Pro 预览版
        #     # vertexai=True,  # 启用 Vertex AI
        #     # project="buysmart-gemini-1",  # GCP 项目 ID
        #     # location="us-central1",  # 区域
        #     # Gemini 3 使用 thinking_level 替代 thinking_budget
        #     # thinking_config={"thinking_level": 0 },
        #      thinking_config={"thinking_budget": 0},  # 禁用思考模式
        # ),
        # 使用 OpenAI 兼容模式调用 Gemini（更灵活，便于切换模型）
        llm=openai.LLM(
            model="gemini-3-pro-preview",
            # model="gemini-2.5-flash",  # grok-4-fast-non-reasoning：禁用思考模式的多模态模型
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key=os.getenv("GOOGLE_API_KEY"),
            # reasoning_effort="low",  # 禁用思考模式
            # timeout=30.0
        ),

        # 视频采样器 - 根据用户说话状态自动调整采样频率
        # 用户说话时 1fps，沉默时 0.3fps，平衡性能与成本
        video_sampler=VoiceActivityVideoSampler(
            speaking_fps=1.0,  # 用户说话时每秒采样 1 帧
            silent_fps=0.3  # 用户沉默时每秒采样 0.3 帧
        ),
    )

    # ========== 注册 conversation_item_added 事件 - 捕获完整 LLM 响应 ==========
    async def _handle_conversation_item_added(event: ConversationItemAddedEvent):
        """
        异步处理对话项添加事件
        
        当用户消息或 Agent 响应被添加到对话历史时触发。
        我们只关心 role="assistant" 的消息，用于保存 GPT 结果到后端。
        
        Args:
            event: ConversationItemAddedEvent，包含 item (ChatMessage)
        """
        try:
            message = event.item
            
            # 只处理 assistant 的消息（LLM 响应）
            if message.role != "assistant":
                return
            
            # 获取完整的响应文本
            full_response = message.text_content or ""
            
            if not full_response:
                logger.warning("⚠️  conversation_item_added: assistant 响应为空")
                return
            
            logger.info("=" * 60)
            logger.info("📨 conversation_item_added 触发 - LLM 响应完成")
            logger.info(f"📝 完整响应 (前200字): {full_response[:200]}...")
            logger.info(f"📏 响应长度: {len(full_response)} 字符")
            logger.info(f"🔇 是否被中断: {message.interrupted}")
            logger.info("=" * 60)
            
            # 检查是否有 pingback 数据
            if not agent._last_pingback:
                logger.warning("⚠️  没有 pingback 数据，跳过保存")
                return
            
            # 从 Agent 实例获取用户上下文（已从房间名称解析）
            user_context = agent.get_user_context()
            logger.info(f"👤 使用用户上下文: user_id={user_context['user_id']}, avatar_id={user_context['avatar_id']}")
            
            # 获取视频帧
            screen_frame = agent._video_frames.get("screen_share")
            camera_frame = agent._video_frames.get("camera")
            
            # 并行分析两个视频帧（如果存在）
            screen_frame_text = None
            camera_frame_text = None
            
            # 构建并行任务列表
            analysis_tasks = []
            task_names = []
            
            if screen_frame:
                logger.info("🖥️  检测到屏幕分享帧，准备分析...")
                analysis_tasks.append(agent.analyze_screen(screen_frame))
                task_names.append("screen_share")
            else:
                logger.info("📷 没有屏幕分享帧")
            
            if camera_frame:
                logger.info("📹 检测到摄像头帧，准备分析...")
                analysis_tasks.append(agent.analyze_screen(camera_frame))
                task_names.append("camera")
            else:
                logger.info("📷 没有摄像头帧")
            
            # 并行执行分析任务
            if analysis_tasks:
                logger.info(f"🔄 开始并行分析 {len(analysis_tasks)} 个视频帧...")
                results = await asyncio.gather(*analysis_tasks, return_exceptions=True)
                
                for i, result in enumerate(results):
                    task_name = task_names[i]
                    if isinstance(result, Exception):
                        logger.error(f"❌ {task_name} 分析失败: {result}")
                    elif result:
                        if task_name == "screen_share":
                            screen_frame_text = result
                            logger.info(f"✅ 屏幕分析完成 (前100字): {screen_frame_text[:100]}...")
                        elif task_name == "camera":
                            camera_frame_text = result
                            logger.info(f"✅ 摄像头分析完成 (前100字): {camera_frame_text[:100]}...")
                    else:
                        logger.warning(f"⚠️  {task_name} 分析返回空")
            
            # 调用 saveGptResult API 保存完整响应
            # gpt_result: Agent LLM（Gemini）对用户的回复
            # screen_frame_text: 屏幕分析的结果
            # camera_frame_text: 摄像头分析的结果
            success = await agent.save_gpt_result(
                gpt_result=full_response,
                pingback=agent._last_pingback,
                user_context=user_context,
                screen_frame_text=screen_frame_text,
                camera_frame_text=camera_frame_text
            )
            
            if success:
                logger.info("✅ LLM 完整响应已保存到后端")
            else:
                logger.warning("⚠️  保存 LLM 响应失败")
                
        except Exception as e:
            logger.error(f"❌ conversation_item_added 处理异常: {e}", exc_info=True)

    @session.on("conversation_item_added")
    def on_conversation_item_added(event: ConversationItemAddedEvent):
        """
        同步事件回调 - 当对话项被添加到历史时触发
        
        LiveKit 事件系统要求使用同步回调，在内部使用 asyncio.create_task 来执行异步操作。
        """
        asyncio.create_task(_handle_conversation_item_added(event))

    # ========== 注册 agent_speech_started 事件 - 记录 TTS 开始时间 ==========
    @session.on("agent_speech_started")
    def on_agent_speech_started(event):
        """
        当 Agent 开始说话（TTS 开始播放）时触发
        
        记录 TTS 开始播放时间，用于计算端到端延迟
        """
        logger.info("🎵 agent_speech_started 事件触发 - TTS 开始播放")
        agent.record_tts_started()

    # 启动会话
    await session.start(agent=agent, room=ctx.room)

    # 验证 Agent 类型和配置
    logger.info("=" * 80)
    logger.info(f"✅ AgentSession 已启动！")
    logger.info(f"🤖 使用的 Agent 类型: {type(agent).__name__}")
    logger.info(f"🎥 Agent 的活跃视频源: {agent._active_video_sources}")
    logger.info(
        f"📹 视频帧状态: camera={agent._video_frames.get('camera') is not None}, screen_share={agent._video_frames.get('screen_share') is not None}")
    logger.info(f"📡 已注册 conversation_item_added 事件监听")
    logger.info("=" * 80)

    # 连接到房间
    await ctx.connect()

    # 订阅视频轨道以捕获视频帧
    @ctx.room.on("track_subscribed")
    def on_track_subscribed(
            track: rtc.Track,
            publication: rtc.TrackPublication,
            participant: rtc.RemoteParticipant,
    ):
        """当订阅到新轨道时的回调"""
        if track.kind == rtc.TrackKind.KIND_VIDEO:
            # 根据 publication.source 判断视频源类型
            # LiveKit 的 TrackSource 枚举值（protobuf 枚举）：
            # - SOURCE_UNKNOWN (0): 未知
            # - SOURCE_CAMERA (1): 摄像头
            # - SOURCE_MICROPHONE (2): 麦克风
            # - SOURCE_SCREENSHARE (3): 屏幕分享
            # - SOURCE_SCREENSHARE_AUDIO (4): 屏幕分享音频
            source = publication.source

            # 将 LiveKit 的 source 枚举映射到我们的字符串标识
            source_camera = rtc.TrackSource.Value('SOURCE_CAMERA')
            source_screenshare = rtc.TrackSource.Value('SOURCE_SCREENSHARE')

            if source == source_camera:
                source_type = "camera"
            elif source == source_screenshare:
                source_type = "screen_share"
            else:
                source_type = "camera"  # 默认为摄像头

            logger.info(
                f"订阅到视频轨道: participant={participant.identity}, "
                f"source={source}, type={source_type}"
            )

            # 创建任务来处理视频流，传入源类型
            asyncio.create_task(
                _process_video_track(track, agent, source_type)  # type: ignore
            )

    # 检查是否已经有视频轨道
    for participant in ctx.room.remote_participants.values():
        for publication in participant.track_publications.values():
            if (
                    publication.subscribed
                    and publication.track
                    and publication.track.kind == rtc.TrackKind.KIND_VIDEO
            ):
                # 同样判断源类型
                source = publication.source
                source_camera = rtc.TrackSource.Value('SOURCE_CAMERA')
                source_screenshare = rtc.TrackSource.Value('SOURCE_SCREENSHARE')

                if source == source_camera:
                    source_type = "camera"
                elif source == source_screenshare:
                    source_type = "screen_share"
                else:
                    source_type = "camera"

                logger.info(
                    f"发现已存在的视频轨道: participant={participant.identity}, "
                    f"source={source}, type={source_type}"
                )
                asyncio.create_task(
                    _process_video_track(publication.track, agent, source_type)
                )

    logger.info("Agent 已成功启动并连接到房间")

async def _process_video_track(
        track: rtc.VideoTrack,
        agent: VisionAgent,
        source_type: str = "camera"
):
    """
    处理视频轨道，持续更新最新的视频帧

    Args:
        track: 视频轨道
        agent: VisionAgent 实例
        source_type: 视频源类型 ("camera" 或 "screen_share")
    """
    video_stream = rtc.VideoStream(track)
    logger.info(f"开始处理 {source_type} 视频流...")

    try:
        async for event in video_stream:
            # 更新 agent 对应源的最新视频帧
            agent.update_video_frame(source_type, event.frame)
            # logger.debug(
            #     f"更新 {source_type} 视频帧: "
            #     f"{event.frame.width}x{event.frame.height}"
            # )
    except Exception as e:
        logger.error(f"处理 {source_type} 视频流时出错: {e}")
    finally:
        logger.info(f"{source_type} 视频流处理结束")


if __name__ == "__main__":
    # 加载环境变量
    load_dotenv()

    logger.info("启动 LiveKit Agent Worker...")

    # 运行 Agent Worker
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
        )
    )
