"""
LiveKit Agent Worker - 语音助手服务入口

该服务集成了多种 AI 能力：
- STT (语音识别): 支持 OpenAI、阿里云
- TTS (语音合成): 支持 MiniMax、ElevenLabs、阿里云
- LLM (大语言模型): 支持 Gemini、OpenAI、阿里云

环境变量配置参考 docs/REFACTOR_PLAN.md
"""

import logging
from dotenv import load_dotenv

from livekit.agents import WorkerOptions, cli

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


def main():
    """主入口函数"""
    # 加载环境变量
    load_dotenv()
    
    logger.info("🚀 启动 LiveKit Agent Worker...")
    
    # 导入入口函数
    from livekit_agent.core import entrypoint
    
    # 运行 Agent Worker
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
        )
    )


if __name__ == "__main__":
    main()
