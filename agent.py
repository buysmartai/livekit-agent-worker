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
import logging
from dotenv import load_dotenv
import os
from typing import Optional
import json
from datetime import datetime

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
from livekit.agents.voice import Agent, AgentSession, VoiceActivityVideoSampler
from livekit.plugins import aliyun

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
            "camera": None,      # 摄像头轨道的最新帧
            "screen_share": None # 屏幕分享轨道的最新帧
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
        logger.debug(f"🖼️  更新 {source_type} 视频帧: {frame.width}x{frame.height}")

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

    async def switch_mode(self, mode: str) -> None:
        """
        切换 Agent 模式，动态调整 instructions

        Args:
            mode: 模式类型
                - "general": 通用对话模式
                - "detail": 详细分析模式
                - "guide": 引导教学模式
                - "security": 安全监控模式
        """
        self._mode = mode

        instructions_map = {
            "general": (
                "你是一个友好的 AI 语音助手，具备视觉分析能力。"
                "你可以看到用户的视频画面，并能够描述和分析画面内容。"
                "当用户询问关于画面的问题时，请基于图像内容给出准确的回答。"
                "请用简洁、清晰的语言与用户交流。"
            ),
            "detail": (
                "你是一个专业的视觉分析助手。"
                "请详细描述画面中的所有元素，包括：物体、颜色、位置、数量、状态等。"
                "提供结构化的分析，从整体到细节逐步说明。"
                "使用专业术语，但保持易于理解。"
            ),
            "guide": (
                "你是一个耐心的教学助手，具备视觉引导能力。"
                "观察用户的操作画面，提供逐步指导和建议。"
                "当用户做得对时给予鼓励，遇到问题时提供解决方案。"
                "用温和、支持性的语气进行交流。"
            ),
            "security": (
                "你是一个安全监控助手。"
                "密切关注画面中的异常情况，如：陌生人、危险行为、物品遗失等。"
                "发现问题时立即提醒，保持警觉但避免误报。"
                "使用简洁、紧急的语气传达重要信息。"
            )
        }

        new_instructions = instructions_map.get(mode, instructions_map["general"])
        await self.update_instructions(new_instructions)
        logger.info(f"已切换到 {mode} 模式，instructions 已更新")

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

    async def on_user_turn_completed(
        self,
        turn_ctx: llm.ChatContext,
        new_message: llm.ChatMessage
    ) -> None:
        """
        在用户完成说话后、LLM 响应前的钩子函数

        功能：
        1. 搜索并注入相关记忆（RAG）
        2. 添加视频帧到消息中（支持多个视频源）
        """
        logger.info("=" * 80)
        logger.info("🔔 VisionAgent.on_user_turn_completed 被调用！")
        logger.info("=" * 80)

        # 获取用户文本内容
        user_text = new_message.text_content or ""
        logger.info(f"📝 用户输入: {user_text}")

        # ========== 1. 调用 REST API 获取动态 prompt ==========
        if self._http_client:
            # 从环境变量或上下文获取用户信息
            user_id = os.getenv("USER_ID", "default_user")
            avatar_id = os.getenv("AVATAR_ID", "default_avatar")
            session_id = os.getenv("SESSION_ID", "default_session")

            logger.info(f"🔄 准备调用 getChatPrompt API...")

            prompt_result = await self.get_dynamic_prompt(
                user_text=user_text,
                user_id=user_id,
                avatar_id=avatar_id,
                session_id=session_id
            )

            if prompt_result:
                # 获取返回的数据
                data = prompt_result.get("data", {})
                pingback = prompt_result.get("pingback", {})
                api_messages = data.get("messages", [])

                # 保存 pingback 数据（用于后续调用 saveGptResult）
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

                                # 使用 update_instructions 更新 Agent 的 system prompt
                                await self.update_instructions(system_text)
                                logger.info("✅ System prompt 已动态更新")

                # 可选：记录其他配置信息
                max_tokens = data.get("maxOutputTokens", "N/A")
                temperature = data.get("temperature", "N/A")
                logger.info(f"⚙️  LLM 配置: maxOutputTokens={max_tokens}, temperature={temperature}")
            else:
                logger.warning("⚠️  未能获取动态 prompt，使用默认配置")

        # ========== 2. 视觉增强：添加活跃视频源的帧 ==========
        image_contents = []
        logger.info(f"🎥 活跃视频源: {self._active_video_sources}")

        for source_type in self._active_video_sources:
            frame = self._video_frames.get(source_type)
            if frame is not None:
                logger.info(
                    f"✅ {source_type} 视频帧已捕获: {frame.width}x{frame.height}"
                )

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
                if isinstance(new_message.content, str):
                    new_message.content = [new_message.content + source_description]
                elif isinstance(new_message.content, list):
                    # 修改第一个文本内容
                    for i, c in enumerate(new_message.content):
                        if isinstance(c, str):
                            new_message.content[i] = c + source_description
                            break

            # 转换为列表格式
            if isinstance(new_message.content, str):
                new_message.content = [new_message.content]
            elif not isinstance(new_message.content, list):
                new_message.content = []

            # 添加所有图像内容
            for source_type, image_content in image_contents:
                # 检查是否已经添加了该源的图片（避免重复）
                has_image = any(
                    isinstance(c, llm.ImageContent) for c in new_message.content
                )
                if not has_image or len(image_contents) > 1:
                    new_message.content.append(image_content)
                    logger.info(f"✅ {source_type} 图像已添加到消息内容")

            logger.info(
                f"🚀 最终消息内容包含: {len([c for c in new_message.content if isinstance(c, str)])} 个文本, "
                f"{len([c for c in new_message.content if isinstance(c, llm.ImageContent)])} 个图像"
            )
        else:
            logger.warning("⚠️  没有可用的视频帧，仅发送文本内容")


        await super().on_user_turn_completed(turn_ctx, new_message)


async def entrypoint(ctx: JobContext):
    """
    Agent 入口函数
    
    当 LiveKit 房间创建或 Agent 被调用时，该函数会被执行。
    """
    logger.info(f"连接到房间: {ctx.room.name}")

    # 创建支持视觉分析的 Agent 实例
    # instructions 参数定义了助手的行为和角色
    agent = VisionAgent(
        instructions=(
            "你是一个友好的 AI 语音助手，具备视觉分析能力。"
            "你可以看到用户的视频画面，并能够描述和分析画面内容。"
            "当用户询问关于画面的问题（如'你看到了什么'、'这是什么'）时，"
            "请基于你看到的图像内容给出详细、准确的回答。"
            "请用简洁、清晰的语言与用户交流。"
            "如果画面模糊或无法识别，请诚实地告知用户。"
        )
    )

    # 创建 Agent 会话，配置语音和语言模型组件
    session = AgentSession(
        # 语音识别 (STT) - 使用阿里云 Paraformer 实时语音识别
        stt=aliyun.STT(
            model="paraformer-realtime-v2",  # 实时语音识别模型
            # vocabulary_id="your_vocabulary_id",  # 可选：热词表 ID，提高特定词汇识别准确率
        ),

        # 语音合成 (TTS) - 使用阿里云 CosyVoice 语音合成
        tts=aliyun.TTS(
            model="cosyvoice-v2",  # CosyVoice v2 模型
            voice="Longwan_v2",  # 语音类型：龙城
            speech_rate=1,  # 语速：1.0 为正常速度 (0.5-2.0)
            # 注意：当前版本的 aliyun.TTS 不支持 pitch_rate 和 volume 参数
        ),

        # 大语言模型 (LLM) - 使用支持视觉的 Qwen-VL 模型
        llm=aliyun.LLM(
            model="qwen-vl-max",  # Qwen-VL-Max 支持图像输入
            # 其他可选模型：qwen-vl-plus (更快但精度稍低)
        ),

        # 视频采样器 - 根据用户说话状态自动调整采样频率
        # 用户说话时 1fps，沉默时 0.3fps，平衡性能与成本
        video_sampler=VoiceActivityVideoSampler(
            speaking_fps=1.0,   # 用户说话时每秒采样 1 帧
            silent_fps=0.3      # 用户沉默时每秒采样 0.3 帧
        ),
    )

    # 启动会话
    await session.start(agent=agent, room=ctx.room)

    # 验证 Agent 类型和配置
    logger.info("=" * 80)
    logger.info(f"✅ AgentSession 已启动！")
    logger.info(f"🤖 使用的 Agent 类型: {type(agent).__name__}")
    logger.info(f"🎥 Agent 的活跃视频源: {agent._active_video_sources}")
    logger.info(f"📹 视频帧状态: camera={agent._video_frames.get('camera') is not None}, screen_share={agent._video_frames.get('screen_share') is not None}")
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


    # ========== 动态调整 Instructions 示例 ==========
    #
    # 示例 1: 在 5 秒后切换到详细分析模式
    # await asyncio.sleep(5)
    # await agent.switch_mode("detail")
    # logger.info("已切换到详细分析模式")
    #
    # 示例 2: 根据用户命令切换模式
    # @session.on("user_input_transcribed")
    # async def on_user_command(event):
    #     text = event.text.lower()
    #     if "详细模式" in text or "详细分析" in text:
    #         await agent.switch_mode("detail")
    #     elif "引导模式" in text or "教学模式" in text:
    #         await agent.switch_mode("guide")
    #     elif "监控模式" in text or "安全模式" in text:
    #         await agent.switch_mode("security")
    #     elif "普通模式" in text or "通用模式" in text:
    #         await agent.switch_mode("general")
    #
    # 示例 3: 使用 FunctionTool 让 LLM 自主切换模式
    # from livekit.agents.llm import function_tool
    #
    # @function_tool
    # async def switch_analysis_mode(mode: str):
    #     """
    #     切换视觉分析模式
    #
    #     Args:
    #         mode: 模式类型，可选 "general", "detail", "guide", "security"
    #     """
    #     await agent.switch_mode(mode)
    #     return f"已切换到 {mode} 模式"
    #
    # # 然后在创建 Agent 时添加这个工具：
    # # agent = VisionAgent(
    # #     instructions="...",
    # #     tools=[switch_analysis_mode]
    # # )
    #
    # ============================================


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
