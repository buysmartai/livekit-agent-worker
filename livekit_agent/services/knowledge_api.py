"""
Knowledge API 客户端

用于上传屏幕帧到后端知识库。
"""

import base64
from typing import Optional, List
from datetime import datetime
import os

from .base_client import BaseAPIClient
from ..config import APIConfig
from ..models import UserContext
from ..utils.logger import get_logger

logger = get_logger("services.knowledge_api")


class KnowledgeAPIClient(BaseAPIClient):
    """Knowledge API 客户端"""
    
    def __init__(self, config: Optional[APIConfig] = None):
        """
        初始化 Knowledge API 客户端
        
        Args:
            config: API 配置，如果为 None 则从环境变量读取
        """
        if config is None:
            config = APIConfig(
                base_url=os.getenv("CHAT_API_BASE_URL", ""),
                api_key=os.getenv("CHAT_API_KEY", ""),
                timeout=float(os.getenv("CHAT_API_TIMEOUT", "30")),
            )
        super().__init__(config)
    
    async def update_vv_knowledge(
        self,
        user_context: UserContext,
        images: List[bytes],
    ) -> bool:
        """
        上传屏幕帧到知识库
        
        Args:
            user_context: 用户上下文
            images: 图片数据列表（PNG 编码的 bytes）
            
        Returns:
            是否上传成功
        """
        if not self.is_available:
            logger.warning("⚠️  Knowledge API 客户端不可用")
            return False
        
        if not images:
            logger.warning("⚠️  没有图片需要上传")
            return False
        
        # 将图片编码为 base64
        images_base64 = []
        for img_bytes in images:
            try:
                img_base64 = base64.b64encode(img_bytes).decode('utf-8')
                images_base64.append(img_base64)
            except Exception as e:
                logger.error(f"❌ 图片 base64 编码失败: {e}")
                continue
        
        if not images_base64:
            logger.warning("⚠️  所有图片编码失败")
            return False
        
        # 构建请求数据
        now = datetime.now()
        data = {
            "reqId": f"{user_context.session_id}_{int(now.timestamp() * 1000)}",
            "timezone": user_context.timezone,
            "appOs": os.getenv("APP_OS", "livekit-agent"),
            "appVersion": os.getenv("APP_VERSION", "1.0.0"),
            "userLocalTime": now.strftime("%Y-%m-%d %H:%M:%S"),
            "userId": user_context.user_id,
            "avatarId": user_context.avatar_id,
            "sessionId": user_context.session_id,
            "images": images_base64,
        }
        
        logger.info(f"📤 上传屏幕帧到知识库: userId={user_context.user_id}, images={len(images_base64)}")
        
        try:
            response, latency = await self._request(
                method="POST",
                endpoint="/voiceChat/updateVvKnowledge",
                data=data,
                timeout=30.0,
            )
            
            if response and response.get("code") == "0":
                logger.info(f"✅ 屏幕帧上传成功 (耗时: {latency:.0f}ms)")
                return True
            else:
                error_msg = response.get("msg", "未知错误") if response else "请求失败"
                logger.warning(f"⚠️  屏幕帧上传失败: {error_msg}")
                return False
                
        except Exception as e:
            logger.error(f"❌ 屏幕帧上传异常: {e}")
            return False
