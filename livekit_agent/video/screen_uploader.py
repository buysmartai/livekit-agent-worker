"""
屏幕帧上传器

每隔一定时间上传屏幕分享帧到后端。
"""

import asyncio
from typing import Optional

from livekit import rtc
from livekit.agents import utils
from livekit.agents.utils.images import EncodeOptions

from .frame_manager import VideoFrameManager
from ..services.knowledge_api import KnowledgeAPIClient
from ..models import UserContext
from ..utils.logger import get_logger

logger = get_logger("video.screen_uploader")


class ScreenUploader:
    """
    屏幕帧上传器
    
    定期从 VideoFrameManager 获取屏幕分享帧，
    编码为 PNG 后上传到后端。
    """
    
    DEFAULT_INTERVAL = 3.0  # 默认上传间隔（秒）
    
    def __init__(
        self,
        frame_manager: VideoFrameManager,
        user_context: UserContext,
        knowledge_client: Optional[KnowledgeAPIClient] = None,
        upload_interval: float = DEFAULT_INTERVAL,
    ):
        """
        初始化屏幕帧上传器
        
        Args:
            frame_manager: 视频帧管理器
            user_context: 用户上下文
            knowledge_client: Knowledge API 客户端
            upload_interval: 上传间隔（秒）
        """
        self._frame_manager = frame_manager
        self._user_context = user_context
        self._knowledge_client = knowledge_client or KnowledgeAPIClient()
        self._upload_interval = upload_interval
        
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        logger.info(f"✅ ScreenUploader 初始化完成，上传间隔: {upload_interval}s")
    
    @property
    def is_running(self) -> bool:
        """检查上传器是否在运行"""
        return self._running
    
    def start(self) -> None:
        """启动上传循环"""
        if self._running:
            logger.warning("⚠️  ScreenUploader 已经在运行")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._upload_loop())
        logger.info("🚀 ScreenUploader 已启动")
    
    def stop(self) -> None:
        """停止上传循环"""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None
        logger.info("🛑 ScreenUploader 已停止")
    
    async def _upload_loop(self) -> None:
        """上传循环"""
        logger.info(f"🔄 开始屏幕帧上传循环，间隔: {self._upload_interval}s")
        
        while self._running:
            try:
                await self._upload_screen_frame()
            except asyncio.CancelledError:
                logger.info("📤 上传循环被取消")
                break
            except Exception as e:
                logger.error(f"❌ 上传循环异常: {e}", exc_info=True)
            
            # 等待下一次上传
            try:
                await asyncio.sleep(self._upload_interval)
            except asyncio.CancelledError:
                break
        
        logger.info("📤 上传循环已结束")
    
    async def _upload_screen_frame(self) -> None:
        """上传单帧屏幕分享"""
        # 获取屏幕分享帧
        screen_frame: Optional[rtc.VideoFrame] = self._frame_manager.get_frame(
            VideoFrameManager.SOURCE_SCREEN_SHARE
        )
        
        if screen_frame is None:
            logger.debug("⏭️  没有屏幕分享帧，跳过上传")
            return
        
        try:
            # 编码为 PNG
            encode_options = EncodeOptions(format="PNG")
            encoded_data = utils.images.encode(screen_frame, encode_options)
            
            if encoded_data is None:
                logger.warning("⚠️  屏幕帧编码失败")
                return
            
            logger.info(f"📸 屏幕帧已编码为 PNG，大小: {len(encoded_data)} bytes")
            
            # 上传到后端
            success = await self._knowledge_client.update_vv_knowledge(
                user_context=self._user_context,
                images=[encoded_data],
            )
            
            if success:
                logger.debug("✅ 屏幕帧上传成功")
            else:
                logger.warning("⚠️  屏幕帧上传失败")
                
        except Exception as e:
            logger.error(f"❌ 屏幕帧处理异常: {e}", exc_info=True)
    
    async def close(self) -> None:
        """关闭上传器并释放资源"""
        self.stop()
        if self._knowledge_client:
            await self._knowledge_client.close()
        logger.info("🔒 ScreenUploader 已关闭")
