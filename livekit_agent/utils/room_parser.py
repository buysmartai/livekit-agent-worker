"""
房间名称解析模块

解析 LiveKit 房间名称，提取用户信息。
"""

from datetime import datetime
from typing import Optional

from ..models.user_context import UserContext
from .logger import get_logger

logger = get_logger("utils.room_parser")


class RoomNameParser:
    """
    房间名称解析器
    
    支持的格式:
    - {userId}_{avatarId}_{language}_{timestamp}: 完整格式（4段）
    - {userId}_{avatarId}_{timestamp}: 旧格式（3段，language 默认 en）
    - {userId}_{avatarId}: 双段格式（自动生成 session_id）
    - 其他: 作为 session_id
    """
    
    def parse(self, room_name: str) -> UserContext:
        """
        解析房间名称
        
        Args:
            room_name: 房间名称
            
        Returns:
            UserContext 实例
            
        Examples:
            >>> parser = RoomNameParser()
            >>> ctx = parser.parse("abc123_def456_1701590400")
            >>> ctx.user_id
            'abc123'
            >>> ctx.avatar_id
            'def456'
            >>> ctx.session_id
            '1701590400'
        """
        context = UserContext(room_name=room_name)
        
        if not room_name:
            logger.warning("⚠️  房间名称为空，使用默认用户信息")
            return context
        
        try:
            parts = room_name.split('_')
            
            if len(parts) >= 4:
                # 新格式: userId_avatarId_language_timestamp
                context.user_id = parts[0]
                context.avatar_id = parts[1]
                context.language = parts[2]
                context.session_id = '_'.join(parts[3:])
                context.is_valid = True
                
                logger.info(f"✅ 从房间名称解析用户信息成功:")
                logger.info(f"   📛 房间名称: {room_name}")
                logger.info(f"   👤 user_id: {context.user_id}")
                logger.info(f"   🎭 avatar_id: {context.avatar_id}")
                logger.info(f"   🌐 language: {context.language}")
                logger.info(f"   🔑 session_id: {context.session_id}")
                
            elif len(parts) == 3:
                # 旧格式: userId_avatarId_timestamp（language 默认 en）
                context.user_id = parts[0]
                context.avatar_id = parts[1]
                context.session_id = parts[2]
                context.language = "en"
                context.is_valid = True
                
                logger.info(f"✅ 从房间名称解析用户信息成功（旧格式）:")
                logger.info(f"   📛 房间名称: {room_name}")
                logger.info(f"   👤 user_id: {context.user_id}")
                logger.info(f"   🎭 avatar_id: {context.avatar_id}")
                logger.info(f"   🌐 language: {context.language} (默认)")
                logger.info(f"   🔑 session_id: {context.session_id}")
                
            elif len(parts) == 2:
                # 兼容格式: userId_avatarId（没有时间戳）
                context.user_id = parts[0]
                context.avatar_id = parts[1]
                context.language = "en"
                context.session_id = str(int(datetime.now().timestamp()))
                context.is_valid = True
                
                logger.warning(f"⚠️  房间名称只有2段，自动生成 session_id:")
                logger.info(f"   👤 user_id: {context.user_id}")
                logger.info(f"   🎭 avatar_id: {context.avatar_id}")
                logger.info(f"   🌐 language: {context.language} (默认)")
                logger.info(f"   🔑 session_id: {context.session_id} (自动生成)")
                
            else:
                # 无法解析，使用房间名称作为 session_id
                logger.warning(f"⚠️  无法解析房间名称 '{room_name}'，格式不符合 userId_avatarId_timestamp")
                context.session_id = room_name
                
        except Exception as e:
            logger.error(f"❌ 解析房间名称异常: {e}")
        
        return context
