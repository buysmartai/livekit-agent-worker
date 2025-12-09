"""
API 响应数据模型

定义后端 API 响应的数据结构。
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class PingbackData:
    """Pingback 数据（用于保存 GPT 结果）"""
    prompt_id: str = ""
    raw_data: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "PingbackData":
        """从字典创建 PingbackData"""
        if not data:
            return cls()
        return cls(
            prompt_id=data.get("promptId", ""),
            raw_data=data,
        )
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return self.raw_data


@dataclass
class MessageContent:
    """消息内容"""
    role: str
    content: Any  # 可以是 str 或 list
    
    @classmethod
    def from_dict(cls, data: dict) -> "MessageContent":
        return cls(
            role=data.get("role", ""),
            content=data.get("content", ""),
        )
    
    def get_text(self) -> str:
        """提取纯文本内容"""
        if isinstance(self.content, str):
            return self.content
        elif isinstance(self.content, list):
            text_parts = []
            for item in self.content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
                elif isinstance(item, str):
                    text_parts.append(item)
            return " ".join(text_parts)
        return ""


@dataclass
class PromptResponse:
    """getChatPrompt API 响应"""
    success: bool = False
    messages: List[MessageContent] = field(default_factory=list)
    pingback: PingbackData = field(default_factory=PingbackData)
    max_output_tokens: Optional[int] = None
    temperature: Optional[float] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_api_response(cls, result: dict) -> "PromptResponse":
        """
        从 API 响应创建 PromptResponse
        
        Args:
            result: API 返回的完整响应
            
        Returns:
            PromptResponse 实例
        """
        data = result.get("data", {})
        
        # 解析 messages
        messages = []
        for msg_data in data.get("messages", []):
            messages.append(MessageContent.from_dict(msg_data))
        
        return cls(
            success=True,
            messages=messages,
            pingback=PingbackData.from_dict(result.get("pingback")),
            max_output_tokens=data.get("maxOutputTokens"),
            temperature=data.get("temperature"),
            raw_data=result,
        )
    
    def get_system_prompt(self) -> Optional[str]:
        """提取 system prompt"""
        for msg in self.messages:
            if msg.role == "system":
                return msg.get_text()
        return None


@dataclass
class VoiceInfo:
    """Avatar 语音信息"""
    voice_api_id: str = ""
    audio_url: str = ""
    description: str = ""
    tags: str = ""
    elevenlabs_api_id: str = ""
    
    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "VoiceInfo":
        """从字典创建 VoiceInfo"""
        if not data:
            return cls()
        return cls(
            voice_api_id=data.get("voiceApiId", ""),
            audio_url=data.get("audioUrl", ""),
            description=data.get("description", ""),
            tags=data.get("tags", ""),
            elevenlabs_api_id=data.get("elevenlabApiId", ""),
        )
    
    @property
    def is_valid(self) -> bool:
        """检查是否有有效的 voice_id"""
        return bool(self.voice_api_id)
