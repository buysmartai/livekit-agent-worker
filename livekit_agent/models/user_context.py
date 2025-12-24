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
    language: str = "en"  # 语言代码，如 en, zh, zh-CN 等
    session_id: str = "default_session"
    room_name: str = ""
    timezone: str = field(default_factory=lambda: os.getenv("TIMEZONE", "America/New_York"))
    is_valid: bool = False
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "user_id": self.user_id,
            "avatar_id": self.avatar_id,
            "language": self.language,
            "session_id": self.session_id,
            "room_name": self.room_name,
            "timezone": self.timezone,
        }
    
    def is_chinese(self) -> bool:
        """判断是否为中文语言"""
        return self.language.lower().startswith("zh")
    
    def __repr__(self) -> str:
        return (
            f"UserContext(user_id={self.user_id!r}, "
            f"avatar_id={self.avatar_id!r}, "
            f"language={self.language!r}, "
            f"session_id={self.session_id!r})"
        )
