"""
视频帧管理器

管理多个视频源的视频帧存储和访问。
"""

from typing import Optional, Dict, List, Set

from ..utils.logger import get_logger

logger = get_logger("video.frame_manager")


class VideoFrameManager:
    """
    视频帧管理器
    
    支持管理多个视频源（摄像头、屏幕分享等）的视频帧。
    """
    
    # 支持的视频源类型
    SOURCE_CAMERA = "camera"
    SOURCE_SCREEN_SHARE = "screen_share"
    
    def __init__(self):
        """初始化视频帧管理器"""
        self._frames: Dict[str, any] = {
            self.SOURCE_CAMERA: None,
            self.SOURCE_SCREEN_SHARE: None,
        }
        self._active_sources: Set[str] = {self.SOURCE_CAMERA, self.SOURCE_SCREEN_SHARE}
        self._mode: str = "general"
        
        logger.info(f"✅ VideoFrameManager 初始化完成，活跃视频源: {self._active_sources}")
    
    @property
    def active_sources(self) -> Set[str]:
        """获取活跃的视频源列表"""
        return self._active_sources
    
    @property
    def mode(self) -> str:
        """获取当前模式"""
        return self._mode
    
    def set_active_sources(self, sources: List[str]) -> None:
        """
        设置活跃的视频源
        
        Args:
            sources: 视频源列表，如 ["camera", "screen_share"]
        """
        self._active_sources = set(sources)
        logger.info(f"已设置活跃视频源: {sources}")
    
    def set_mode(self, mode: str, video_sources: Optional[List[str]] = None) -> None:
        """
        设置工作模式
        
        Args:
            mode: 模式名称，如 "general", "screen_analysis", "dual_view"
            video_sources: 该模式下使用的视频源列表
            
        Examples:
            >>> manager.set_mode("general", ["camera"])
            >>> manager.set_mode("screen_analysis", ["screen_share"])
            >>> manager.set_mode("dual_view", ["camera", "screen_share"])
        """
        self._mode = mode
        if video_sources is not None:
            self.set_active_sources(video_sources)
        logger.info(f"模式已设置为: {mode}, 活跃视频源: {self._active_sources}")
    
    def update_frame(self, source_type: str, frame) -> None:
        """
        更新指定来源的视频帧
        
        Args:
            source_type: 视频源类型 ("camera" 或 "screen_share")
            frame: 视频帧对象 (rtc.VideoFrame)
        """
        self._frames[source_type] = frame
        # logger.debug(f"🖼️  更新 {source_type} 视频帧")
    
    def get_frame(self, source_type: str):
        """
        获取指定来源的视频帧
        
        Args:
            source_type: 视频源类型
            
        Returns:
            视频帧对象，如果不存在返回 None
        """
        return self._frames.get(source_type)
    
    def get_active_frames(self) -> Dict[str, any]:
        """
        获取所有活跃视频源的帧
        
        Returns:
            {source_type: frame} 字典，只包含有帧的活跃源
        """
        result = {}
        for source in self._active_sources:
            frame = self._frames.get(source)
            if frame is not None:
                result[source] = frame
        return result
    
    def has_any_frame(self) -> bool:
        """检查是否有任何视频帧"""
        return any(f is not None for f in self._frames.values())
    
    def has_active_frame(self) -> bool:
        """检查是否有活跃源的视频帧"""
        return any(
            self._frames.get(source) is not None 
            for source in self._active_sources
        )
    
    def clear_frame(self, source_type: str) -> None:
        """清除指定来源的视频帧"""
        self._frames[source_type] = None
    
    def clear_all_frames(self) -> None:
        """清除所有视频帧"""
        for key in self._frames:
            self._frames[key] = None
    
    # 向后兼容方法
    @property
    def last_video_frame(self):
        """获取最后一个视频帧（向后兼容）"""
        return self._frames.get(self.SOURCE_CAMERA)
    
    @last_video_frame.setter
    def last_video_frame(self, frame):
        """设置最后一个视频帧（向后兼容）"""
        self._frames[self.SOURCE_CAMERA] = frame
