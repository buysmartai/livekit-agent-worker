"""
VisionAgent - 支持视觉分析的自定义 Agent

这是 Agent 的核心实现，整合了：
- 视频多模态分析
- 动态 prompt 注入
- REST API 集成
- 延迟统计
"""

from __future__ import annotations

from typing import Optional, AsyncIterable, Union, List
import asyncio

from livekit.agents.voice import Agent, ModelSettings
from livekit.agents import llm

from ..services import ChatAPIClient, UserAPIClient, VisionAPIClient
from ..video import VideoFrameManager
from ..utils import LatencyTracker, RoomNameParser, get_logger
from ..models import UserContext, PromptResponse, PingbackData
from ..config import get_settings

logger = get_logger("core.vision_agent")

# 尝试导入 SDK 的 update_instructions 函数
try:
    from livekit.agents.voice.generation import update_instructions as sdk_update_instructions
    HAS_SDK_UPDATE_INSTRUCTIONS = True
except ImportError:
    HAS_SDK_UPDATE_INSTRUCTIONS = False
    logger.warning("⚠️  无法导入 sdk_update_instructions，将使用手动方式更新 chat_ctx")


class VisionAgent(Agent):
    """
    支持视觉分析的自定义 Agent
    
    功能特性：
    - 视频多模态分析（摄像头 + 屏幕分享）
    - 动态 prompt 注入
    - REST API 集成
    - 延迟统计
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        logger.info("🚀 VisionAgent 实例正在初始化...")
        
        settings = get_settings()
        
        # 服务层
        self._chat_api = ChatAPIClient(settings.chat_api)
        self._user_api = UserAPIClient(settings.chat_api)
        self._vision_api = VisionAPIClient(settings.vision_api)
        
        # 视频帧管理
        self._frame_manager = VideoFrameManager()
        
        # 延迟统计
        self._latency_tracker = LatencyTracker()
        
        # 房间名称解析
        self._room_parser = RoomNameParser()
        
        # 用户上下文
        self._user_context = UserContext()
        
        # 最后一次 API 调用的 pingback 数据
        self._last_pingback: Optional[PingbackData] = None
        
        logger.info(f"✅ VisionAgent 初始化完成！活跃视频源: {self._frame_manager.active_sources}")
    
    # ========== 属性访问器（向后兼容） ==========
    
    @property
    def _video_frames(self):
        """向后兼容：返回视频帧字典"""
        return {
            "camera": self._frame_manager.get_frame("camera"),
            "screen_share": self._frame_manager.get_frame("screen_share"),
        }
    
    @property
    def _active_video_sources(self):
        """向后兼容：返回活跃视频源"""
        return self._frame_manager.active_sources
    
    # ========== 用户上下文管理 ==========
    
    def set_user_info_from_room_name(self, room_name: str) -> bool:
        """
        从房间名称解析用户信息
        
        Args:
            room_name: 房间名称
            
        Returns:
            是否解析成功
        """
        self._user_context = self._room_parser.parse(room_name)
        return self._user_context.is_valid
    
    def get_user_context(self) -> dict:
        """获取用户上下文字典"""
        return self._user_context.to_dict()
    
    @property
    def _user_id(self) -> str:
        return self._user_context.user_id
    
    @property
    def _avatar_id(self) -> str:
        return self._user_context.avatar_id
    
    # ========== 视频帧管理 ==========
    
    def update_video_frame(self, source_type: str, frame) -> None:
        """更新视频帧（向后兼容）"""
        self._frame_manager.update_frame(source_type, frame)
    
    def set_active_video_sources(self, sources: list) -> None:
        """设置活跃视频源"""
        self._frame_manager.set_active_sources(sources)
    
    def set_mode(self, mode: str, video_sources: list = None) -> None:
        """设置工作模式"""
        self._frame_manager.set_mode(mode, video_sources)
    
    # ========== 延迟统计 ==========
    
    def record_tts_started(self) -> None:
        """记录 TTS 开始播放时间"""
        self._latency_tracker.record_tts_started()
    
    # ========== API 调用 ==========
    
    async def get_avatar_voice_info(self, avatar_id: str, user_id: str = "default_user"):
        """获取 Avatar 语音配置"""
        voice_info = await self._user_api.get_avatar_voice_info(avatar_id, user_id)
        if voice_info:
            return {
                "voiceApiId": voice_info.voice_api_id,
                "audioUrl": voice_info.audio_url,
                "description": voice_info.description,
            }
        return None
    
    async def analyze_screen(self, frame, user_input: str = "") -> Optional[str]:
        """分析屏幕内容"""
        return await self._vision_api.analyze_video_frame(frame, user_input)
    
    async def save_gpt_result(
        self,
        gpt_result: str,
        pingback: dict,
        user_context: dict = None,
        screen_frame_text: str = None,
        camera_frame_text: str = None,
    ) -> bool:
        """保存 GPT 结果（向后兼容接口）"""
        # 转换参数
        pingback_data = PingbackData.from_dict(pingback)
        ctx = UserContext(**user_context) if user_context else self._user_context
        
        return await self._chat_api.save_gpt_result(
            gpt_result=gpt_result,
            pingback=pingback_data,
            user_context=ctx,
            screen_frame_text=screen_frame_text,
            camera_frame_text=camera_frame_text,
        )
    
    # ========== LLM 节点 ==========
    
    def _manual_update_chat_ctx_system(self, chat_ctx: llm.ChatContext, system_text: str) -> None:
        """手动更新 chat_ctx 中的 system message"""
        found_system = False
        for i, item in enumerate(chat_ctx.items):
            if isinstance(item, llm.ChatMessage) and item.role == "system":
                item.content = [system_text]
                found_system = True
                logger.info(f"✅ 已手动更新 chat_ctx 中的 system message (index={i})")
                break
        
        if not found_system:
            new_system_msg = llm.ChatMessage(
                role="system",
                content=[system_text],
            )
            chat_ctx.items.insert(0, new_system_msg)
            logger.info("✅ 已在 chat_ctx 开头插入新的 system message")
    
    def _extract_user_text(self, chat_ctx: llm.ChatContext) -> str:
        """从 chat_ctx 提取最新的用户文本"""
        for item in reversed(chat_ctx.items):
            if isinstance(item, llm.ChatMessage) and item.role == "user":
                return item.text_content or ""
        return ""
    
    def _add_video_frames_to_message(self, chat_ctx: llm.ChatContext) -> None:
        """将视频帧添加到用户消息"""
        # 查找用户消息
        user_message = None
        for item in reversed(chat_ctx.items):
            if isinstance(item, llm.ChatMessage) and item.role == "user":
                user_message = item
                break
        
        if not user_message:
            return
        
        # 获取活跃帧
        active_frames = self._frame_manager.get_active_frames()
        if not active_frames:
            logger.warning("⚠️  没有可用的视频帧")
            return
        
        image_contents = []
        for source_type, frame in active_frames.items():
            logger.info(f"✅ {source_type} 视频帧已捕获: {frame.width}x{frame.height}")
            
            settings = get_settings()
            image_content = llm.ImageContent(
                image=frame,
                inference_width=settings.video.inference_width,
                inference_height=settings.video.inference_height,
            )
            image_contents.append((source_type, image_content))
        
        if not image_contents:
            return
        
        logger.info(f"📸 准备将 {len(image_contents)} 个视频源的图像添加到消息")
        
        # 转换用户消息内容为列表格式
        if isinstance(user_message.content, str):
            user_message.content = [user_message.content]
        elif not isinstance(user_message.content, list):
            user_message.content = []
        
        # 添加图像
        for source_type, image_content in image_contents:
            user_message.content.append(image_content)
            logger.info(f"✅ {source_type} 图像已添加到消息内容")
    
    async def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: List[llm.FunctionTool],
        model_settings: ModelSettings,
    ) -> AsyncIterable[Union[llm.ChatChunk, str]]:
        """
        LLM 节点 - 拦截所有用户输入
        
        这是 Agent pipeline 中处理 LLM 推理的核心节点。
        """
        logger.info("=" * 80)
        logger.info("🔔 VisionAgent.llm_node 被调用！")
        logger.info("=" * 80)
        
        # 1. 开始延迟统计
        user_text = self._extract_user_text(chat_ctx)
        self._latency_tracker.start_turn(user_text)
        logger.info(f"📝 用户输入: {user_text}")
        logger.info(f"👤 用户上下文: {self._user_context}")
        
        # 2. 获取动态 prompt
        if self._chat_api.is_available:
            logger.info(f"🔄 准备调用 getChatPrompt API...")
            
            prompt_result = await self._chat_api.get_dynamic_prompt(
                user_text=user_text,
                user_context=self._user_context,
            )
            
            if prompt_result:
                # 记录 API 延迟到 LatencyTracker
                self._latency_tracker.record_api_latency(prompt_result.elapsed_ms)
                
                # 保存 pingback
                self._last_pingback = prompt_result.pingback
                logger.info(f"💾 保存 pingback 数据，promptId={prompt_result.pingback.prompt_id}")
                
                # 更新 system prompt
                system_prompt = prompt_result.get_system_prompt()
                if system_prompt:
                    logger.info(f"🎭 动态更新 system prompt (前100字): {system_prompt[:100]}...")
                    
                    if HAS_SDK_UPDATE_INSTRUCTIONS:
                        try:
                            sdk_update_instructions(chat_ctx, instructions=system_prompt, add_if_missing=True)
                            logger.info("✅ 已通过 SDK 函数更新 chat_ctx")
                        except Exception as e:
                            logger.warning(f"⚠️  SDK update_instructions 失败: {e}")
                            self._manual_update_chat_ctx_system(chat_ctx, system_prompt)
                    else:
                        self._manual_update_chat_ctx_system(chat_ctx, system_prompt)
                    
                    # 更新 Agent 内部状态
                    await self.update_instructions(system_prompt)
                
                # 添加预填充消息（跳过思考链）
                thinking_done_msg = llm.ChatMessage(
                    role="assistant",
                    content=["""<think>  
    内部隐性推理链已完成。所有必要判断、路径选择与上下文分析均已结束。  
    本阶段标记为"结束"，不再继续展开。  
</think>"""]
                )
                chat_ctx.items.append(thinking_done_msg)
                logger.info("🧠 已添加预填充 Assistant 消息（跳过思考链）")
            else:
                logger.warning("⚠️  未能获取动态 prompt，使用默认配置")
        
        # 3. 添加视频帧
        self._add_video_frames_to_message(chat_ctx)
        
        # 4. 调用 LLM
        is_first_token = True
        async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
            if is_first_token:
                self._latency_tracker.record_llm_first_token()
                is_first_token = False
            yield chunk
        
        # 5. 记录完成时间
        self._latency_tracker.record_llm_complete()
    
    # ========== 资源清理 ==========
    
    async def close(self) -> None:
        """关闭所有资源"""
        await self._chat_api.close()
        await self._user_api.close()
        await self._vision_api.close()
        logger.info("✅ VisionAgent 资源已清理")
