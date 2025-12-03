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
from dotenv import load_dotenv
import os
from typing import Optional, AsyncIterable, Any
import json
from datetime import datetime
from livekit.plugins import elevenlabs
from livekit.plugins.elevenlabs import VoiceSettings

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
)
from livekit.agents.voice import Agent, AgentSession, VoiceActivityVideoSampler, ModelSettings
from livekit.agents.utils import images
from livekit.plugins import aliyun, google

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
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        logger.info("🚀 VisionAgent 实例正在初始化...")

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

        logger.info(f"✅ VisionAgent 初始化完成！活跃视频源: {self._active_video_sources}")

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

            if response.status_code == 200:
                result = response.json()
                if result.get("code") == "0":
                    logger.info(f"✅ 获取动态 prompt 成功")

                    # 返回完整的响应数据
                    return {
                        "data": result.get("data", {}),
                        "pingback": result.get("pingback", {}),
                        "messages": result.get("messages", [])
                    }
                else:
                    logger.warning(f"⚠️  API 返回错误码: {result.get('code')}")
                    return None
            else:
                logger.error(f"❌ API 请求失败: HTTP {response.status_code}")
                logger.error(f"响应内容: {response.text[:200]}")
                return None

        except httpx.TimeoutException:
            logger.error("❌ getChatPrompt API 超时（10秒）")
            return None
        except Exception as e:
            logger.error(f"❌ getChatPrompt API 调用异常: {e}", exc_info=True)
            return None

    async def analyze_screen_with_gemini(self, frame: rtc.VideoFrame) -> Optional[str]:
        """
        使用 Gemini Flash 2.5 多模态模型分析屏幕内容

        Args:
            frame: 视频帧

        Returns:
            提取的文本/描述内容，如果失败返回 None
        """
        try:
            import google.generativeai as genai
            from PIL import Image

            # 配置 Gemini API
            gemini_api_key = os.getenv("GEMINI_API_KEY", "")
            if not gemini_api_key:
                logger.error("❌ [Gemini] GEMINI_API_KEY 未配置")
                return None

            genai.configure(api_key=gemini_api_key)

            # 使用 LiveKit 官方 API 将 VideoFrame 转换为 JPEG bytes
            # 这会自动处理 YUV/I420 等格式到 RGBA 的转换
            logger.info(f"🔄 [Gemini] 转换视频帧: {frame.width}x{frame.height}, type={frame.type}")

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

            # 从 JPEG bytes 创建 PIL Image
            pil_image = Image.open(io.BytesIO(jpeg_bytes))

            logger.info(f"🔍 [Gemini] 开始分析屏幕内容 ({pil_image.width}x{pil_image.height})...")

            # 使用 Gemini Flash 2.5
            model = genai.GenerativeModel('gemini-2.5-flash')

            prompt = (
                "Please analyze this screen/image carefully. "
                "Extract all visible text content and describe what's shown in the image. "
                "Format your response as:\n"
                "[Text Content]: (all visible text)\n"
                "[Description]: (what's shown in the image)"
            )

            response = model.generate_content([prompt, pil_image])

            if response and response.text:
                result_text = response.text
                logger.info(f"✅ [Gemini] 分析完成 (前100字): {result_text[:100]}...")
                return result_text
            else:
                logger.warning("⚠️  [Gemini] 未返回内容")
                return None

        except ImportError as e:
            logger.error(f"❌ [Gemini] 缺少依赖库: {e}")
            logger.error("请安装: pip install google-generativeai pillow")
            return None
        except Exception as e:
            logger.error(f"❌ [Gemini] 分析失败: {e}", exc_info=True)
            return None

    async def save_gpt_result(
            self,
            gpt_result: str,
            pingback: dict,
            user_context: Optional[dict] = None,
            screen_frame_text: Optional[str] = None
    ) -> bool:
        """
        调用后端 REST API 保存 GPT 生成的结果（并行处理，不阻塞主流程）

        Args:
            gpt_result: LLM 生成的文本（这里是 Gemini 分析的结果）
            pingback: getChatPrompt 返回的 pingback 数据
            user_context: 用户上下文（包含 userId, avatarId, sessionId, timezone）
            screen_frame_text: 屏幕分享的文本内容

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
                "imgPay": "N",
                "isVipImg": "N",
                "pingback": pingback
            }

            logger.info(f"💾 [并行] 调用 saveGptResult API...")
            logger.info(f"   GPT Result (前50字): {gpt_result[:50]}...")
            if screen_frame_text:
                logger.info(f"   Screen Text (前50字): {screen_frame_text[:50]}...")

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

    async def process_video_memory_async(
            self,
            pingback: dict,
            user_context: dict,
            video_frame: rtc.VideoFrame,
            video_source: str
    ):
        """
        异步处理视频记忆（并行任务，不阻塞主流程）

        Args:
            pingback: getChatPrompt 返回的 pingback 数据（快照，避免竞态条件）
            user_context: 用户上下文（userId, avatarId, sessionId 等）
            video_frame: 要分析的视频帧（快照）
            video_source: 视频来源 ("camera" 或 "screen_share")

        工作流程：
        1. 使用 Gemini Flash 2.5 分析图片内容
        2. 调用 saveGptResult API 保存

        此方法在后台运行，不影响对话响应速度
        """
        try:
            if not pingback:
                logger.debug("⚠️  [并行] 没有 pingback 数据，跳过视频记忆处理")
                return

            if not video_frame:
                logger.debug("⚠️  [并行] 没有可用的视频帧，跳过处理")
                return

            logger.info(f"🔄 [并行] 开始处理视频记忆... (来源: {video_source})")

            # 使用 Gemini 分析视频内容
            video_analysis = await self.analyze_screen_with_gemini(video_frame)

            if not video_analysis:
                logger.warning("⚠️  [并行] Gemini 分析失败，跳过保存")
                return

            # 调用 saveGptResult API（使用快照的 pingback 和 user_context）
            success = await self.save_gpt_result(
                gpt_result=video_analysis,
                pingback=pingback,
                user_context=user_context,
                screen_frame_text=video_analysis
            )

            if success:
                logger.info("✅ [并行] 视频记忆处理完成并已保存")
            else:
                logger.warning("⚠️  [并行] 视频记忆保存失败")

        except Exception as e:
            logger.error(f"❌ [并行] 视频记忆处理异常: {e}", exc_info=True)

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

        # 准备用户上下文（用于后续 API 调用）
        user_id = os.getenv("USER_ID", "default_user")
        avatar_id = os.getenv("AVATAR_ID", "default_avatar")
        session_id = os.getenv("SESSION_ID", "default_session")
        timezone = os.getenv("TIMEZONE", "Asia/Shanghai")

        user_context = {
            "user_id": user_id,
            "avatar_id": avatar_id,
            "session_id": session_id,
            "timezone": timezone
        }

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

        async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
            yield chunk


async def entrypoint(ctx: JobContext):
    """
    Agent 入口函数
    
    当 LiveKit 房间创建或 Agent 被调用时，该函数会被执行。
    """
    logger.info(f"连接到房间: {ctx.room.name}")

    # 创建支持视觉分析的 Agent 实例
    # instructions 参数定义了助手的行为和角色
    agent = VisionAgent(
        instructions=()
    )

    # 创建 Agent 会话，配置语音和语言模型组件
    session = AgentSession(
        # 语音识别 (STT) - 使用阿里云 Paraformer 实时语音识别
        stt=aliyun.STT(
            model="paraformer-realtime-v2",  # 实时语音识别模型
            # vocabulary_id="your_vocabulary_id",  # 可选：热词表 ID，提高特定词汇识别准确率
        ),

        # 语音合成 (TTS) - 使用阿里云 CosyVoice 语音合成
        # tts=aliyun.TTS(
        #     model="cosyvoice-v2",  # CosyVoice v2 模型
        #     voice="Longwan_v2",  # 语音类型：龙城
        #     speech_rate=1,  # 语速：1.0 为正常速度 (0.5-2.0)
        #     # 注意：当前版本的 aliyun.TTS 不支持 pitch_rate 和 volume 参数
        # ),
        tts=elevenlabs.TTS(
            voice_id="tQ4MEZFJOzsahSEEZtHK",
            model="eleven_turbo_v2_5",
            voice_settings=VoiceSettings(
                stability=0.5,              # 稳定性 (0.0-1.0)
                similarity_boost=0.75,      # 相似度 (0.0-1.0)
                speed=1.2,                  # 语速 (0.8-1.2) - 设置为最快
                use_speaker_boost=True      # 使用说话人增强
            ),
        ),

        # 大语言模型 (LLM) - 使用 Google Gemini 多模态模型
        llm=google.LLM(
            model="gemini-2.5-flash",  # Gemini 2.0 Flash 支持图像/视频输入
            # 其他可选模型：gemini-1.5-pro, gemini-1.5-flash
        ),

        # 视频采样器 - 根据用户说话状态自动调整采样频率
        # 用户说话时 1fps，沉默时 0.3fps，平衡性能与成本
        video_sampler=VoiceActivityVideoSampler(
            speaking_fps=1.0,  # 用户说话时每秒采样 1 帧
            silent_fps=0.3  # 用户沉默时每秒采样 0.3 帧
        ),
    )

    # 启动会话
    await session.start(agent=agent, room=ctx.room)

    # 验证 Agent 类型和配置
    logger.info("=" * 80)
    logger.info(f"✅ AgentSession 已启动！")
    logger.info(f"🤖 使用的 Agent 类型: {type(agent).__name__}")
    logger.info(f"🎥 Agent 的活跃视频源: {agent._active_video_sources}")
    logger.info(
        f"📹 视频帧状态: camera={agent._video_frames.get('camera') is not None}, screen_share={agent._video_frames.get('screen_share') is not None}")
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
