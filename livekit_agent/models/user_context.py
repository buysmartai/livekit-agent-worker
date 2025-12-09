"""
用户上下文数据模型

存储从房间名称解析出的用户信息。
"""

from dataclasses import dataclass, field
from typing import Optional
import os


@dataclass
class UserContext:
    """用户上下文"""
    user_id: str = "default_user"
    avatar_id: str = "default_avatar"
    session_id: str = "default_session"
    room_name: str = ""
    timezone: str = field(default_factory=lambda: os.getenv("TIMEZONE", "Asia/Shanghai"))
    is_valid: bool = False
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "user_id": self.user_id,
            "avatar_id": self.avatar_id,
            "session_id": self.session_id,
            "room_name": self.room_name,
            "timezone": self.timezone,
        }
    
    def __repr__(self) -> str:
        return (
            f"UserContext(user_id={self.user_id!r}, "
            f"avatar_id={self.avatar_id!r}, "
            f"session_id={self.session_id!r})"
        )
