"""
LLM 提供商工厂

支持多种 LLM 提供商的动态切换。
"""

from enum import Enum
from typing import Any, Optional

from ..config import LLMConfig
from ..utils.logger import get_logger

logger = get_logger("providers.llm")


class LLMProvider(Enum):
    """LLM 提供商枚举"""
    OPENAI = "openai"
    GOOGLE_GEMINI = "google_gemini"
    GEMINI_VIA_OPENAI = "gemini_via_openai"
    GROK = "grok"
    ALIYUN = "aliyun"


class LLMProviderFactory:
    """LLM 提供商工厂"""
    
    @staticmethod
    def create(config: LLMConfig) -> Any:
        """
        根据配置创建 LLM 实例
        
        Args:
            config: LLM 配置
            
        Returns:
            LLM 实例
            
        Raises:
            ValueError: 未知的提供商类型
            
        Examples:
            >>> config = LLMConfig(
            ...     provider="gemini_via_openai",
            ...     model="gemini-3-pro-preview",
            ...     base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            ...     api_key="your-api-key"
            ... )
            >>> llm = LLMProviderFactory.create(config)
        """
        provider = config.provider.lower()
        kwargs = config.to_kwargs()
        
        logger.info(f"🤖 创建 LLM 实例: provider={provider}, model={config.model}")
        
        if provider == LLMProvider.OPENAI.value:
            from livekit.plugins import openai
            return openai.LLM(**kwargs)
        
        elif provider == LLMProvider.GOOGLE_GEMINI.value:
            from livekit.plugins import google
            return google.LLM(**kwargs)
        
        elif provider == LLMProvider.GEMINI_VIA_OPENAI.value:
            # 使用 OpenAI 兼容模式调用 Gemini
            from livekit.plugins import openai
            return openai.LLM(**kwargs)
        
        elif provider == LLMProvider.GROK.value:
            # Grok 使用 OpenAI 兼容 API
            from livekit.plugins import openai
            return openai.LLM(**kwargs)
        
        elif provider == LLMProvider.ALIYUN.value:
            from livekit.plugins import aliyun
            return aliyun.LLM(**kwargs)
        
        else:
            raise ValueError(f"Unknown LLM provider: {provider}")
    
    @staticmethod
    def create_from_env() -> Any:
        """从环境变量创建 LLM 实例"""
        from ..config import get_settings
        settings = get_settings()
        return LLMProviderFactory.create(settings.llm)
