"""
视频轨道处理器

处理 LiveKit 视频轨道，持续更新视频帧。
"""

import asyncio
from typing import Callable, Optional

from livekit import rtc

from .frame_manager import VideoFrameManager
from ..utils.logger import get_logger

logger = get_logger("video.track_processor")


def get_source_type_from_publication(publication: rtc.TrackPublication) -> str:
    """
    从 TrackPublication 获取视频源类型
    
    Args:
        publication: LiveKit TrackPublication
        
    Returns:
        视频源类型字符串 ("camera" 或 "screen_share")
    """
    source = publication.source
    
    # LiveKit 的 TrackSource 枚举值（protobuf 枚举）
    source_camera = rtc.TrackSource.Value('SOURCE_CAMERA')
    source_screenshare = rtc.TrackSource.Value('SOURCE_SCREENSHARE')
    
    if source == source_camera:
        return VideoFrameManager.SOURCE_CAMERA
    elif source == source_screenshare:
        return VideoFrameManager.SOURCE_SCREEN_SHARE
    else:
        # 默认为摄像头
        return VideoFrameManager.SOURCE_CAMERA


async def process_video_track(
    track: rtc.VideoTrack,
    frame_manager: VideoFrameManager,
    source_type: str = "camera",
    on_frame: Optional[Callable] = None,
) -> None:
    """
    处理视频轨道，持续更新视频帧
    
    Args:
        track: 视频轨道
        frame_manager: 视频帧管理器
        source_type: 视频源类型 ("camera" 或 "screen_share")
        on_frame: 可选的帧回调函数
    """
    video_stream = rtc.VideoStream(track)
    logger.info(f"开始处理 {source_type} 视频流...")
    
    try:
        async for event in video_stream:
            # 更新帧管理器
            frame_manager.update_frame(source_type, event.frame)
            
            # 调用可选的回调
            if on_frame:
                try:
                    on_frame(source_type, event.frame)
                except Exception as e:
                    logger.error(f"帧回调异常: {e}")
                    
    except Exception as e:
        logger.error(f"处理 {source_type} 视频流时出错: {e}")
    finally:
        logger.info(f"{source_type} 视频流处理结束")


def setup_track_subscription(
    room: rtc.Room,
    frame_manager: VideoFrameManager,
) -> None:
    """
    设置视频轨道订阅
    
    为房间的 track_subscribed 事件注册处理函数
    
    Args:
        room: LiveKit 房间
        frame_manager: 视频帧管理器
    """
    @room.on("track_subscribed")
    def on_track_subscribed(
        track: rtc.Track,
        publication: rtc.TrackPublication,
        participant: rtc.RemoteParticipant,
    ):
        if track.kind == rtc.TrackKind.KIND_VIDEO:
            source_type = get_source_type_from_publication(publication)
            
            logger.info(
                f"📹 订阅到视频轨道: participant={participant.identity}, "
                f"source={publication.source}, type={source_type}"
            )
            
            # 创建任务来处理视频流
            asyncio.create_task(
                process_video_track(track, frame_manager, source_type)
            )
    
    @room.on("track_unsubscribed")
    def on_track_unsubscribed(
        track: rtc.Track,
        publication: rtc.TrackPublication,
        participant: rtc.RemoteParticipant,
    ):
        """当轨道取消订阅时，清除对应的视频帧缓存"""
        if track.kind == rtc.TrackKind.KIND_VIDEO:
            source_type = get_source_type_from_publication(publication)
            
            logger.info(
                f"🚫 视频轨道已取消订阅: participant={participant.identity}, "
                f"source={publication.source}, type={source_type}"
            )
            
            # 清除对应的视频帧
            frame_manager.clear_frame(source_type)
            logger.info(f"🗑️  已清除 {source_type} 视频帧缓存")
    
    logger.info("✅ 视频轨道订阅已设置")


def process_existing_tracks(
    room: rtc.Room,
    frame_manager: VideoFrameManager,
) -> None:
    """
    处理房间中已存在的视频轨道
    
    Args:
        room: LiveKit 房间
        frame_manager: 视频帧管理器
    """
    for participant in room.remote_participants.values():
        for publication in participant.track_publications.values():
            if (
                publication.subscribed
                and publication.track
                and publication.track.kind == rtc.TrackKind.KIND_VIDEO
            ):
                source_type = get_source_type_from_publication(publication)
                
                logger.info(
                    f"发现已存在的视频轨道: participant={participant.identity}, "
                    f"source={publication.source}, type={source_type}"
                )
                
                asyncio.create_task(
                    process_video_track(publication.track, frame_manager, source_type)
                )
