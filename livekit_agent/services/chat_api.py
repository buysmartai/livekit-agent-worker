"""
Chat API 客户端

处理 getChatPrompt 和 saveGptResult 接口调用。
"""

from typing import Optional
import os

from .base_client import BaseAPIClient
from ..config import APIConfig
from ..models import UserContext, PromptResponse, PingbackData
from ..utils.logger import get_logger

logger = get_logger("services.chat_api")


class ChatAPIClient(BaseAPIClient):
    """Chat API 客户端"""
    
    async def get_dynamic_prompt(
        self,
        user_text: str,
        user_context: UserContext,
    ) -> Optional[PromptResponse]:
        """
        调用 getChatPrompt API 获取动态 prompt
        
        Args:
            user_text: 用户输入的文本
            user_context: 用户上下文
            
        Returns:
            PromptResponse 实例，失败返回 None
        """
        if not self.is_available:
            logger.error("❌ HTTP 客户端未初始化")
            return None
        
        ctx = user_context.to_dict()
        
        request_body = self._build_common_request_body(
            userId=ctx["user_id"],
            avatarId=ctx["avatar_id"],
            sessionId=ctx["session_id"],
            timezone=ctx["timezone"],
            chatStatusType="append",
            agentContext={
                "agentType": "voice_chat",
                "context": {},
            },
            language=os.getenv("LANGUAGE", "en"),
            input=None,
            latestUserInput=[
                {
                    "source": "content",
                    "type": "text",
                    "text": user_text,
                    "image_url": None,
                    "input_audio": None,
                }
            ],
            modelProvider=os.getenv("MODEL_PROVIDER", "vercel"),
            gptModel=os.getenv("GPT_MODEL", "claude-3-7-sonnet-20250219"),
        )
        
        logger.info(f"🌐 调用 getChatPrompt API")
        logger.info(f"📋 请求参数: userId={ctx['user_id']}, avatarId={ctx['avatar_id']}, sessionId={ctx['session_id']}")
        
        result, elapsed_ms = await self._request("POST", "chat/getChatPrompt", request_body)
        logger.info(f"⏱️  getChatPrompt API 耗时: {elapsed_ms:.2f}ms")
        # 将result打印
        logger.debug(f"🔍 getChatPrompt API 返回: {result}")
        
        if result and result.get("code") == "0":
            logger.info(f"✅ 获取动态 prompt 成功 (耗时: {elapsed_ms:.2f}ms)")
            response = PromptResponse.from_api_response(result)
            response.elapsed_ms = elapsed_ms  # 记录 API 耗时
            return response
        else:
            code = result.get("code") if result else "N/A"
            logger.warning(f"⚠️  API 返回错误码: {code} (耗时: {elapsed_ms:.2f}ms)")
            return None
    
    async def save_gpt_result(
        self,
        gpt_result: str,
        pingback: PingbackData,
        user_context: UserContext,
        screen_frame_text: Optional[str] = None,
        camera_frame_text: Optional[str] = None,
    ) -> bool:
        """
        调用 saveGptResult API 保存 GPT 结果
        
        Args:
            gpt_result: LLM 生成的文本
            pingback: Pingback 数据
            user_context: 用户上下文
            screen_frame_text: 屏幕分享帧分析结果
            camera_frame_text: 摄像头帧分析结果
            
        Returns:
            是否保存成功
        """
        if not self.is_available:
            logger.error("❌ HTTP 客户端未初始化")
            return False
        
        if not pingback.raw_data:
            logger.warning("⚠️  没有 pingback 数据，跳过 saveGptResult")
            return False
        
        ctx = user_context.to_dict()
        
        request_body = self._build_common_request_body(
            userId=ctx["user_id"],
            avatarId=ctx["avatar_id"],
            sessionId=ctx["session_id"],
            timezone=ctx["timezone"],
            agentType="voice_chat",
            chatStatusType=None,
            agentContext=None,
            gptResult=gpt_result,
            networkResult=None,
            screenFrameText=screen_frame_text,
            cameraFrameText=camera_frame_text,
            imgPay="N",
            isVipImg="N",
            pingback=pingback.to_dict(),
        )
        
        logger.info(f"💾 调用 saveGptResult API...")
        logger.info(f"   GPT Result (前150字): {gpt_result[:150]}...")
        if screen_frame_text:
            logger.info(f"   Screen Text (前150字): {screen_frame_text[:150]}...")
        if camera_frame_text:
            logger.info(f"   Camera Text (前150字): {camera_frame_text[:150]}...")
        
        result, elapsed_ms = await self._request("POST", "chat/saveGptResult", request_body, timeout=5.0)
        
        if result and result.get("code") == "0":
            logger.info(f"✅ saveGptResult 成功 (耗时: {elapsed_ms:.2f}ms)")
            return True
        else:
            code = result.get("code") if result else "N/A"
            logger.warning(f"⚠️  saveGptResult 失败: {code} (耗时: {elapsed_ms:.2f}ms)")
            return False
