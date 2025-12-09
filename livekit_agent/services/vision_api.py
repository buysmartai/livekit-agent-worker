"""
Vision API 客户端

处理视觉分析相关的 API 调用。
"""

from typing import Optional
import base64

from .base_client import BaseAPIClient
from ..config import APIConfig
from ..utils.logger import get_logger

logger = get_logger("services.vision_api")


class VisionAPIClient(BaseAPIClient):
    """Vision API 客户端（用于屏幕/摄像头分析）"""
    
    def __init__(self, config: APIConfig, model: str = "grok-4-fast-non-reasoning"):
        """
        初始化 Vision API 客户端
        
        Args:
            config: API 配置
            model: 视觉分析模型名称
        """
        super().__init__(config)
        self._model = model
    
    async def analyze_image(
        self,
        image_bytes: bytes,
        user_input: str = "",
        max_tokens: int = 1500,
    ) -> Optional[str]:
        """
        分析图片内容
        
        Args:
            image_bytes: JPEG 图片字节数据
            user_input: 用户的问题（用于生成针对性的 prompt）
            max_tokens: 最大输出 token 数
            
        Returns:
            分析结果文本，失败返回 None
        """
        if not self.is_available:
            logger.error("❌ HTTP 客户端不可用")
            return None
        
        # 将图片转换为 base64
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
        
        # 构建 prompt
        if not user_input:
            user_input = "what is on the screen"
        
        prompt = (
            f'The user is sharing their screen with you and asked "{user_input}".\n'
            "Extract only the on-screen information that may help answer this question.\n"
            "Do NOT provide an answer or recommendation.\n"
            "Output only the extracted information, within 1000 words."
        )
        
        logger.info(f"🔍 开始分析图片内容 (model={self._model})...")
        
        # 构建 OpenAI 兼容的请求
        request_body = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            },
                        },
                    ],
                }
            ],
            "max_tokens": max_tokens,
        }
        
        result, elapsed_ms = await self._request(
            "POST", 
            "chat/completions", 
            request_body,
            timeout=self._config.timeout,
        )
        
        if result:
            choices = result.get("choices", [])
            if choices and len(choices) > 0:
                content = choices[0].get("message", {}).get("content", "")
                if content:
                    logger.info(f"✅ 图片分析完成 (耗时: {elapsed_ms:.2f}ms)")
                    logger.info(f"   结果前100字: {content[:100]}...")
                    return content
                else:
                    logger.warning("⚠️  返回内容为空")
                    return None
            else:
                logger.warning("⚠️  未返回有效的 choices")
                return None
        else:
            return None
    
    async def analyze_video_frame(
        self,
        frame,  # rtc.VideoFrame
        user_input: str = "",
    ) -> Optional[str]:
        """
        分析视频帧
        
        Args:
            frame: LiveKit VideoFrame 对象
            user_input: 用户的问题
            
        Returns:
            分析结果文本，失败返回 None
        """
        try:
            from livekit.agents.utils import images
            
            logger.info(f"🔄 转换视频帧: {frame.width}x{frame.height}")
            
            # 使用 LiveKit 官方 API 将 VideoFrame 转换为 JPEG
            encode_options = images.EncodeOptions(
                format="JPEG",
                quality=85,
                resize_options=images.ResizeOptions(
                    width=1024,
                    height=1024,
                    strategy="scale_aspect_fit",
                ),
            )
            jpeg_bytes = images.encode(frame, encode_options)
            
            return await self.analyze_image(jpeg_bytes, user_input)
            
        except Exception as e:
            logger.error(f"❌ 视频帧分析失败: {e}", exc_info=True)
            return None
