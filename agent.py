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
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_video_frame: rtc.VideoFrame | None = None
        self._video_track: rtc.RemoteVideoTrack | None = None

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
