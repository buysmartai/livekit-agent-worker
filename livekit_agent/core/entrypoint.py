"""
Agent 入口点

定义 LiveKit Agent Worker 的入口函数。
"""

import asyncio
from typing import Optional

from livekit.agents import JobContext, ConversationItemAddedEvent

from .vision_agent import VisionAgent
from .session_factory import create_session
from ..video import VideoFrameManager, process_video_track, setup_track_subscription, process_existing_tracks
from ..utils.logger import get_logger

logger = get_logger("core.entrypoint")


async def entrypoint(ctx: JobContext) -> None:
    """
    Agent 入口函数
    
    当 LiveKit 房间创建或 Agent 被调用时，该函数会被执行。
    
    房间名称格式: {userId}_{avatarId}_{timestamp}
    例如: abc123_def456_1701590400
    
    Args:
        ctx: JobContext，包含房间信息
    """
    room_name = ctx.room.name
    logger.info("=" * 80)
    logger.info(f"🏠 连接到房间: {room_name}")
    logger.info("=" * 80)
    
    # 1. 创建 Agent
    agent = VisionAgent(instructions="")  # 动态从 API 获取
    
    # 2. 从房间名称解析用户信息
    parse_success = agent.set_user_info_from_room_name(room_name)
    if not parse_success:
        logger.warning(f"⚠️  房间名称 '{room_name}' 解析失败，将使用默认用户信息")
    
    # 3. 动态获取 Avatar 语音配置
    voice_id = None
    if agent._avatar_id and agent._avatar_id != "default_avatar":
        logger.info(f"🎤 正在获取 Avatar {agent._avatar_id} 的语音配置...")
        voice_info = await agent.get_avatar_voice_info(agent._avatar_id, agent._user_id)
        if voice_info and voice_info.get("voiceApiId"):
            voice_id = voice_info["voiceApiId"]
            logger.info(f"✅ 使用动态 voice_id: {voice_id}")
        else:
            logger.warning(f"⚠️  无法获取 Avatar 语音配置，使用默认 voice_id")
    
    # 4. 创建 Session
    session = create_session(voice_id=voice_id)
    
    # 5. 注册事件处理
    _register_event_handlers(session, agent)
    
    # 6. 启动会话
    await session.start(agent=agent, room=ctx.room)
    
    logger.info("=" * 80)
    logger.info(f"✅ AgentSession 已启动！")
    logger.info(f"🤖 使用的 Agent 类型: {type(agent).__name__}")
    logger.info(f"🎥 活跃视频源: {agent._frame_manager.active_sources}")
    logger.info("=" * 80)
    
    # 7. 连接到房间
    await ctx.connect()
    
    # 8. 设置视频轨道处理
    setup_track_subscription(ctx.room, agent._frame_manager)
    process_existing_tracks(ctx.room, agent._frame_manager)
    
    logger.info("Agent 已成功启动并连接到房间")


def _register_event_handlers(session, agent: VisionAgent) -> None:
    """
    注册事件处理函数
    
    Args:
        session: AgentSession
        agent: VisionAgent 实例
    """
    
    async def _handle_conversation_item_added(event: ConversationItemAddedEvent):
        """处理对话项添加事件"""
        try:
            message = event.item
            
            # 只处理 assistant 的消息
            if message.role != "assistant":
                return
            
            full_response = message.text_content or ""
            if not full_response:
                logger.warning("⚠️  assistant 响应为空")
                return
            
            logger.info("=" * 60)
            logger.info("📨 conversation_item_added 触发 - LLM 响应完成")
            logger.info(f"📝 完整响应 (前200字): {full_response[:200]}...")
            logger.info(f"📏 响应长度: {len(full_response)} 字符")
            logger.info("=" * 60)
            
            # 检查 pingback
            if not agent._last_pingback or not agent._last_pingback.raw_data:
                logger.warning("⚠️  没有 pingback 数据，跳过保存")
                return
            
            # 获取用户上下文
            user_context = agent.get_user_context()
            
            # 分析视频帧
            screen_frame = agent._frame_manager.get_frame("screen_share")
            camera_frame = agent._frame_manager.get_frame("camera")
            
            analysis_tasks = []
            task_names = []
            
            if screen_frame:
                logger.info("🖥️  检测到屏幕分享帧，准备分析...")
                analysis_tasks.append(agent.analyze_screen(screen_frame))
                task_names.append("screen_share")
            
            if camera_frame:
                logger.info("📹 检测到摄像头帧，准备分析...")
                analysis_tasks.append(agent.analyze_screen(camera_frame))
                task_names.append("camera")
            
            screen_frame_text = None
            camera_frame_text = None
            
            if analysis_tasks:
                logger.info(f"🔄 开始并行分析 {len(analysis_tasks)} 个视频帧...")
                results = await asyncio.gather(*analysis_tasks, return_exceptions=True)
                
                for i, result in enumerate(results):
                    task_name = task_names[i]
                    if isinstance(result, Exception):
                        logger.error(f"❌ {task_name} 分析失败: {result}")
                    elif result:
                        if task_name == "screen_share":
                            screen_frame_text = result
                        elif task_name == "camera":
                            camera_frame_text = result
            
            # 保存结果
            success = await agent.save_gpt_result(
                gpt_result=full_response,
                pingback=agent._last_pingback.to_dict(),
                user_context=user_context,
                screen_frame_text=screen_frame_text,
                camera_frame_text=camera_frame_text,
            )
            
            if success:
                logger.info("✅ LLM 完整响应已保存到后端")
            else:
                logger.warning("⚠️  保存 LLM 响应失败")
                
        except Exception as e:
            logger.error(f"❌ conversation_item_added 处理异常: {e}", exc_info=True)
    
    @session.on("conversation_item_added")
    def on_conversation_item_added(event: ConversationItemAddedEvent):
        asyncio.create_task(_handle_conversation_item_added(event))
    
    @session.on("agent_speech_started")
    def on_agent_speech_started(event):
        logger.info("🎵 agent_speech_started 事件触发 - TTS 开始播放")
        agent.record_tts_started()
    
    logger.info("📡 已注册事件处理函数")
