"""
VisionAgent - 支持视觉分析的自定义 Agent

这是 Agent 的核心实现，整合了：
- 视频多模态分析
- 动态 prompt 注入
- REST API 集成
- 延迟统计
"""

from __future__ import annotations

import numpy as np
from typing import Optional, AsyncIterable, Union, List

from livekit.agents.voice import Agent, ModelSettings
from livekit.agents import llm, stt
from livekit import rtc

from ..services import ChatAPIClient, UserAPIClient, VisionAPIClient
from ..video import VideoFrameManager
from ..utils import LatencyTracker, RoomNameParser, get_logger, AudioDenoiser
from ..models import UserContext, PromptResponse, PingbackData
from ..config import get_settings

logger = get_logger("core.vision_agent")


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
        
        # 音频降噪器 - 通过环境变量控制是否启用
        # AUDIO_DENOISE_ENABLED=true 启用，默认关闭以节省 CPU
        audio_config = settings.audio
        if audio_config.denoise_enabled:
            self._audio_denoiser = AudioDenoiser(
                prop_decrease=audio_config.denoise_strength,
                stationary=True,
                n_fft=audio_config.n_fft,
                hop_length=audio_config.hop_length,
            )
            self._denoise_skip_frames = audio_config.denoise_skip_frames
        else:
            self._audio_denoiser = AudioDenoiser(prop_decrease=0)  # 禁用
            self._audio_denoiser._nr_available = False  # 强制禁用
            self._denoise_skip_frames = 0
        
        self._denoise_log_counter = 0
        self._denoise_frame_counter = 0  # 用于跳帧计数
        self._denoise_log_interval = 500  # 每 500 帧打印一次日志
        
        logger.info(f"✅ VisionAgent 初始化完成！活跃视频源: {self._frame_manager.active_sources}")
        denoise_status = '已启用' if (audio_config.denoise_enabled and self._audio_denoiser.is_available) else '已禁用（节省CPU）'
        logger.info(f"🔊 音频降噪器: {denoise_status}")
    
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
                "elevenlabsApiId": voice_info.elevenlabs_api_id,
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
    
    def _rebuild_chat_ctx_from_api(self, chat_ctx: llm.ChatContext, prompt_result: PromptResponse) -> None:
        """
        使用 API 返回的完整 messages 重建 chat_ctx

        API 返回的 data.messages 包含：
        - system: 完整的 system prompt
        - user: 包含 <user_invisible_guidance>、<creative_rules> 等指令的完整用户消息

        Args:
            chat_ctx: 当前的 ChatContext
            prompt_result: API 返回的 PromptResponse
        """
        # 清空现有的 items
        chat_ctx.items.clear()
        logger.info("🔄 清空 chat_ctx，准备使用 API 返回的 messages 重建")

        # 遍历 API 返回的 messages
        for msg in prompt_result.messages:
            if msg.role == "system":
                # 添加 system message
                system_msg = llm.ChatMessage(
                    role="system",
                    content=[msg.get_text()] if isinstance(msg.content, str) else [msg.get_text()],
                )
                chat_ctx.items.append(system_msg)
                logger.info(f"✅ 添加 system message (前100字): {msg.get_text()[:100]}...")

            elif msg.role == "user":
                # 添加 user message（保留完整的 content 结构）
                # API 返回的 content 可能是 list，包含 type: text 的对象
                if isinstance(msg.content, list):
                    # 提取所有文本内容
                    text_parts = []
                    for item in msg.content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text_parts.append(item.get("text", ""))
                        elif isinstance(item, str):
                            text_parts.append(item)
                    content = "\n".join(text_parts) if text_parts else ""
                else:
                    content = msg.content

                user_msg = llm.ChatMessage(
                    role="user",
                    content=[content],
                )
                chat_ctx.items.append(user_msg)
                logger.info(f"✅ 添加 user message (前200字): {content[:200]}...")

            elif msg.role == "assistant":
                # 添加 assistant message（如果有历史）
                assistant_msg = llm.ChatMessage(
                    role="assistant",
                    content=[msg.get_text()],
                )
                chat_ctx.items.append(assistant_msg)
                logger.info(f"✅ 添加 assistant message")

        logger.info(f"✅ chat_ctx 重建完成，共 {len(chat_ctx.items)} 条消息")

    def _inject_visual_mode_instruction(self, chat_ctx: llm.ChatContext) -> None:
        """
        在用户消息开头注入 visual_input_mode 说明
        
        当用户正在分享屏幕时，在 user prompt 开头添加说明，
        告知 LLM 这是实时屏幕流而非静态截图。
        """
        # 检查是否有屏幕分享帧
        has_screen_share = self._frame_manager.get_frame("screen_share") is not None
        
        if not has_screen_share:
            return
        
        # 查找最后一条用户消息
        user_message = None
        for item in reversed(chat_ctx.items):
            if isinstance(item, llm.ChatMessage) and item.role == "user":
                user_message = item
                break
        
        if not user_message:
            return
        
        # 构建 visual_input_mode 说明
        visual_mode_text = """<visual_input_mode>
- The user is sharing a LIVE mobile screen or participating in a real-time video/screen-sharing session.
- All visual inputs should be treated as a continuous live feed, NOT as static screenshots or photos.
- Do NOT assume the image is a captured moment, posed photo, or intentionally framed picture.
</visual_input_mode>

"""
        
        # 在用户消息内容开头添加
        if isinstance(user_message.content, list) and len(user_message.content) > 0:
            # 内容是列表，找到第一个文本内容并在其开头添加
            for i, content_item in enumerate(user_message.content):
                if isinstance(content_item, str):
                    user_message.content[i] = visual_mode_text + content_item
                    logger.info("✅ 已在 user message 开头注入 visual_input_mode 说明（屏幕分享模式）")
                    break
        elif isinstance(user_message.content, str):
            # 内容是字符串
            user_message.content = visual_mode_text + user_message.content
            logger.info("✅ 已在 user message 开头注入 visual_input_mode 说明（屏幕分享模式）")

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
                
                # 使用 API 返回的完整 messages 重建 chat_ctx
                # 这样可以使用 API 返回的 user message（包含 <user_invisible_guidance> 等指令）
                self._rebuild_chat_ctx_from_api(chat_ctx, prompt_result)

                # 更新 Agent 内部状态的 instructions
                system_prompt = prompt_result.get_system_prompt()
                if system_prompt:
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
        
        # 3. 注入 visual_input_mode 说明（如果有屏幕分享）
        self._inject_visual_mode_instruction(chat_ctx)
        
        # 4. 添加视频帧
        self._add_video_frames_to_message(chat_ctx)
        
        # 5. 调用 LLM
        is_first_token = True
        async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
            if is_first_token:
                self._latency_tracker.record_llm_first_token()
                is_first_token = False
            yield chunk
        
        # 5. 记录完成时间
        self._latency_tracker.record_llm_complete()
    
    # ========== STT 节点（音频预处理） ==========
    
    async def stt_node(
        self,
        audio: AsyncIterable[rtc.AudioFrame],
        model_settings: ModelSettings,
    ) -> Optional[AsyncIterable[stt.SpeechEvent]]:
        """
        STT 节点 - 在语音转文字前对音频进行降噪处理
        
        这个方法拦截原始音频流，应用降噪处理后再传递给 STT 引擎。
        主要目的是过滤远处的声音干扰。
        
        Args:
            audio: 原始音频帧流
            model_settings: 模型设置
            
        Returns:
            STT 事件流
        """
        # 如果降噪器不可用，直接使用默认处理
        if not self._audio_denoiser.is_available:
            logger.debug("降噪器不可用，使用默认 STT 处理")
            return Agent.default.stt_node(self, audio, model_settings)
        
        # 创建降噪后的音频流生成器
        async def denoised_audio_stream() -> AsyncIterable[rtc.AudioFrame]:
            async for frame in audio:
                try:
                    # 跳帧处理：每 N 帧只处理一帧，其他帧直接返回
                    self._denoise_frame_counter += 1
                    if self._denoise_skip_frames > 1 and self._denoise_frame_counter % self._denoise_skip_frames != 0:
                        yield frame
                        continue
                    
                    # 获取帧数据
                    frame_data = frame.data.tobytes()
                    sample_rate = frame.sample_rate
                    num_channels = frame.num_channels
                    samples_per_channel = frame.samples_per_channel
                    
                    # 应用降噪
                    denoised_data = self._audio_denoiser.process_frame(
                        frame_data=frame_data,
                        sample_rate=sample_rate,
                        num_channels=num_channels,
                        samples_per_channel=samples_per_channel,
                    )
                    
                    # 创建新的音频帧
                    denoised_array = np.frombuffer(denoised_data, dtype=np.int16)
                    denoised_frame = rtc.AudioFrame(
                        data=denoised_array,
                        sample_rate=sample_rate,
                        num_channels=num_channels,
                        samples_per_channel=samples_per_channel,
                    )
                    
                    # 定期记录日志
                    self._denoise_log_counter += 1
                    if self._denoise_log_counter % self._denoise_log_interval == 0:
                        logger.debug(f"🔊 已处理 {self._denoise_log_counter} 帧音频（降噪中，跳帧={self._denoise_skip_frames}）")
                    
                    yield denoised_frame
                    
                except Exception as e:
                    # 出错时返回原始帧
                    logger.error(f"❌ 音频帧降噪失败: {e}")
                    yield frame
        
        # 使用降噪后的音频流调用默认 STT 处理
        return Agent.default.stt_node(self, denoised_audio_stream(), model_settings)
    
    # ========== 资源清理 ==========
    
    async def close(self) -> None:
        """关闭所有资源"""
        await self._chat_api.close()
        await self._user_api.close()
        await self._vision_api.close()
        logger.info("✅ VisionAgent 资源已清理")
