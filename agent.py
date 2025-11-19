"""
LiveKit Agent Worker - 阿里云语音助手服务

该服务集成了阿里云的 AI 能力：
- STT (语音识别): Paraformer 实时语音识别
- TTS (语音合成): CosyVoice 文本转语音
- LLM (大语言模型): Qwen 系列模型

环境变量要求:
- DASHSCOPE_API_KEY: 阿里云 DashScope API 密钥
- LIVEKIT_URL: LiveKit 服务器地址（可选）
- LIVEKIT_API_KEY: LiveKit API 密钥（可选）
- LIVEKIT_API_SECRET: LiveKit API 密钥（可选）
"""

import logging
from dotenv import load_dotenv

from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    WorkerOptions,
    cli,
)
from livekit.plugins import aliyun
from livekit.plugins import elevenlabs
from livekit.plugins.elevenlabs import VoiceSettings

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


async def entrypoint(ctx: JobContext):
    """
    Agent 入口函数
    
    当 LiveKit 房间创建或 Agent 被调用时，该函数会被执行。
    """
    logger.info(f"连接到房间: {ctx.room.name}")
    
    # 创建 Agent 实例
    # instructions 参数定义了助手的行为和角色
    agent = Agent(
        instructions=(
            "你是一个友好的 AI 语音助手。"
            "你的任务是以自然、流畅的方式与用户对话。"
            "请用简洁、清晰的语言回答用户的问题。"
            "如果遇到不确定的问题，请诚实地告知用户。"
        )
    )
    
    # 创建 Agent 会话，配置语音和语言模型组件
    session = AgentSession(
        # 语音识别 (STT) - 使用阿里云 Paraformer 实时语音识别
        stt=aliyun.STT(
            model="paraformer-realtime-v2",  # 实时语音识别模型
            # vocabulary_id="your_vocabulary_id",  # 可选：热词表 ID，提高特定词汇识别准确率
        ),
        
        # 语音合成 (TTS) - 使用 ElevenLabs TTS
        tts=elevenlabs.TTS(
            voice_id="tQ4MEZFJOzsahSEEZtHK",
            model="eleven_ttv_v3",
            voice_settings=VoiceSettings(
                stability=0.5,              # 稳定性 (0.0-1.0)
                similarity_boost=0.75,      # 相似度 (0.0-1.0)
                speed=1.2,                  # 语速 (0.8-1.2) - 设置为最快
                use_speaker_boost=True      # 使用说话人增强
            ),
        ),
        
        # 大语言模型 (LLM) - 使用阿里云 Qwen 系列模型
        llm=aliyun.LLM(
            model="qwen-plus",          # Qwen Plus 模型（可选：qwen-max, qwen-turbo）
            # 注意：当前版本的 aliyun.LLM 不支持 temperature 和 max_tokens 参数
            # 这些参数可能需要通过其他方式配置
        ),
    )
    
    # 启动会话
    await session.start(agent=agent, room=ctx.room)
    
    # 连接到房间
    await ctx.connect()
    
    logger.info("Agent 已成功启动并连接到房间")


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
