"""
User API 客户端

处理用户相关接口调用，如获取 Avatar 语音配置。
"""

from typing import Optional
import os

from .base_client import BaseAPIClient
from ..config import APIConfig
from ..models.api_response import VoiceInfo
from ..utils.logger import get_logger

logger = get_logger("services.user_api")


class UserAPIClient(BaseAPIClient):
    """User API 客户端"""
    
    async def get_avatar_voice_info(
        self,
        avatar_id: str,
        user_id: str = "default_user",
    ) -> Optional[VoiceInfo]:
        """
        调用 queryUserAvatarById API 获取 Avatar 的语音配置
        
        Args:
            avatar_id: Avatar ID
            user_id: 用户 ID
            
        Returns:
            VoiceInfo 实例，失败返回 None
        """
        if not self.is_available:
            logger.error("❌ HTTP 客户端未初始化")
            return None
        
        request_body = self._build_common_request_body(
            userId=user_id,
            requestId=os.urandom(16).hex(),
            avatarId=avatar_id,
        )
        
        logger.info(f"🌐 调用 queryUserAvatarById API")
        logger.info(f"📋 请求参数: userId={user_id}, avatarId={avatar_id}")
        
        result, elapsed_ms = await self._request("POST", "user/queryUserAvatarById", request_body)
        logger.info(f"⏱️  queryUserAvatarById API 耗时: {elapsed_ms:.2f}ms")
        
        if result:
            code = result.get("code")
            # 兼容字符串和整数的 code
            if code == "0" or code == 0:
                data = result.get("data", {})
                voice_info = VoiceInfo.from_dict(data.get("voiceInfo"))
                
                if voice_info.is_valid:
                    logger.info(f"✅ 获取 Avatar 语音信息成功:")
                    logger.info(f"   🎤 voiceApiId: {voice_info.voice_api_id}")
                    logger.info(f"   🔊 description: {voice_info.description}")
                    return voice_info
                else:
                    logger.warning(f"⚠️  Avatar {avatar_id} 没有配置 voiceInfo")
                    return None
            else:
                logger.warning(f"⚠️  API 返回错误码: {code} (耗时: {elapsed_ms:.2f}ms)")
                return None
        else:
            return None
