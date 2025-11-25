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

    该 Agent 能够在用户提问时自动捕获视频帧，
    并将图像发送给支持多模态的 LLM 进行分析。

    支持动态调整 instructions 以适应不同场景。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_video_frame: rtc.VideoFrame | None = None
        self._video_track: rtc.RemoteVideoTrack | None = None
        self._mode: str = "general"  # 当前模式：general, detail, guide 等

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

    async def on_user_turn_completed(
        self,
        turn_ctx: llm.ChatContext,
        new_message: llm.ChatMessage
    ) -> None:
        """
        在用户完成说话后、LLM 响应前的钩子函数

        检查是否有可用的视频帧，如果有则添加到用户消息中。
        """
        # 如果有视频帧，添加到新消息中
        if self._last_video_frame is not None:
            # 创建 ImageContent 并添加到用户消息中
            # 使用较小的分辨率以降低成本和延迟
            image_content = llm.ImageContent(
                image=self._last_video_frame,
                inference_width=512,  # 调整为 512 像素宽度
                inference_height=512,  # 调整为 512 像素高度
            )

            # 将图像添加到用户消息内容中
            if isinstance(new_message.content, str):
                new_message.content = [new_message.content, image_content]
            elif isinstance(new_message.content, list):
                # 检查是否已经添加了图片（避免重复）
                has_image = any(
                    isinstance(c, llm.ImageContent) for c in new_message.content
                )
                if not has_image:
                    new_message.content.append(image_content)

            logger.info(
                f"已添加视频帧到 LLM 上下文，分辨率: "
                f"{self._last_video_frame.width}x{self._last_video_frame.height}"
            )

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
            logger.info(
                f"订阅到视频轨道: participant={participant.identity}, "
                f"source={publication.source}"
            )
            # 创建任务来处理视频流（添加类型转换）
            asyncio.create_task(_process_video_track(track, agent))  # type: ignore

    # 检查是否已经有视频轨道
    for participant in ctx.room.remote_participants.values():
        for publication in participant.track_publications.values():
            if (
                publication.subscribed
                and publication.track
                and publication.track.kind == rtc.TrackKind.KIND_VIDEO
            ):
                logger.info(
                    f"发现已存在的视频轨道: participant={participant.identity}"
                )
                asyncio.create_task(_process_video_track(publication.track, agent))

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


async def _process_video_track(track: rtc.VideoTrack, agent: VisionAgent):
    """
    处理视频轨道，持续更新最新的视频帧

    Args:
        track: 视频轨道
        agent: VisionAgent 实例
    """
    video_stream = rtc.VideoStream(track)
    logger.info("开始处理视频流...")

    try:
        async for event in video_stream:
            # 更新 agent 的最新视频帧
            agent._last_video_frame = event.frame
            # logger.debug(f"更新视频帧: {event.frame.width}x{event.frame.height}")
    except Exception as e:
        logger.error(f"处理视频流时出错: {e}")
    finally:
        logger.info("视频流处理结束")


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
