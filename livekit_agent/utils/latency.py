"""
延迟统计模块

提供对话延迟的追踪、记录和报告功能。
"""

from dataclasses import dataclass, field
from typing import Optional, Callable, List
import time

from .logger import get_logger

logger = get_logger("utils.latency")


@dataclass
class LatencyMetrics:
    """延迟统计数据"""
    turn_id: int = 0
    start_time: float = 0.0
    api_latency_ms: float = 0.0
    llm_first_token_time: float = 0.0
    llm_complete_time: float = 0.0
    tts_start_time: float = 0.0
    user_text: str = ""
    
    def get_llm_ttft_ms(self) -> float:
        """获取 LLM 首 Token 延迟 (毫秒)"""
        if self.llm_first_token_time and self.start_time:
            return (self.llm_first_token_time - self.start_time) * 1000
        return 0.0
    
    def get_llm_complete_ms(self) -> float:
        """获取 LLM 完成延迟 (毫秒)"""
        if self.llm_complete_time and self.start_time:
            return (self.llm_complete_time - self.start_time) * 1000
        return 0.0
    
    def get_llm_generation_ms(self) -> float:
        """获取 LLM 生成耗时 (毫秒)，从首 token 到完成"""
        if self.llm_complete_time and self.llm_first_token_time:
            return (self.llm_complete_time - self.llm_first_token_time) * 1000
        return 0.0
    
    def get_tts_startup_ms(self) -> float:
        """获取 TTS 启动延迟 (毫秒)，从 LLM 首 token 到 TTS 开始"""
        # 流式处理：TTS 在 LLM 首 token 后就可能开始，不需要等 LLM 完成
        if self.tts_start_time and self.llm_first_token_time:
            return (self.tts_start_time - self.llm_first_token_time) * 1000
        return 0.0
    
    def get_tts_start_ms(self) -> float:
        """获取 TTS 开始播放延迟 (毫秒)"""
        if self.tts_start_time and self.start_time:
            return (self.tts_start_time - self.start_time) * 1000
        return 0.0
    
    def get_total_latency_ms(self) -> float:
        """获取总延迟 (毫秒)，从用户输入到 TTS 开始播放"""
        if self.tts_start_time and self.start_time:
            return (self.tts_start_time - self.start_time) * 1000
        # 如果 TTS 还没开始，返回 LLM 完成时间
        if self.llm_complete_time and self.start_time:
            return (self.llm_complete_time - self.start_time) * 1000
        return 0.0
    
    def to_dict(self) -> dict:
        """转换为字典（用于日志或 API 上报）"""
        return {
            "turn_id": self.turn_id,
            "api_latency_ms": self.api_latency_ms,
            "llm_ttft_ms": self.get_llm_ttft_ms(),
            "llm_generation_ms": self.get_llm_generation_ms(),
            "llm_complete_ms": self.get_llm_complete_ms(),
            "tts_startup_ms": self.get_tts_startup_ms(),
            "tts_start_ms": self.get_tts_start_ms(),
            "total_latency_ms": self.get_total_latency_ms(),
        }


# 观察者回调类型
LatencyObserver = Callable[[str, LatencyMetrics], None]


class LatencyTracker:
    """延迟追踪器"""
    
    def __init__(self):
        self._current_turn_id: int = 0
        self._metrics: LatencyMetrics = LatencyMetrics()
        self._observers: List[LatencyObserver] = []
    
    @property
    def current_metrics(self) -> LatencyMetrics:
        """获取当前的延迟统计数据"""
        return self._metrics
    
    @property
    def current_turn_id(self) -> int:
        """获取当前轮次 ID"""
        return self._current_turn_id
    
    def add_observer(self, observer: LatencyObserver) -> None:
        """
        添加观察者
        
        Args:
            observer: 回调函数，签名为 (event: str, metrics: LatencyMetrics) -> None
        """
        self._observers.append(observer)
    
    def remove_observer(self, observer: LatencyObserver) -> None:
        """移除观察者"""
        if observer in self._observers:
            self._observers.remove(observer)
    
    def start_turn(self, user_text: str = "") -> LatencyMetrics:
        """
        开始新的对话轮次
        
        Args:
            user_text: 用户输入的文本
            
        Returns:
            新创建的 LatencyMetrics 实例
        """
        self._current_turn_id += 1
        self._metrics = LatencyMetrics(
            turn_id=self._current_turn_id,
            start_time=time.perf_counter(),
            user_text=user_text,
        )
        logger.info(f"⏱️  [延迟统计] Turn #{self._current_turn_id} 开始计时")
        return self._metrics
    
    def record_api_latency(self, latency_ms: float) -> None:
        """记录 API 延迟"""
        self._metrics.api_latency_ms = latency_ms
    
    def record_llm_first_token(self) -> None:
        """记录 LLM 首 Token 时间"""
        self._metrics.llm_first_token_time = time.perf_counter()
        ttft_ms = self._metrics.get_llm_ttft_ms()
        logger.info(f"⏱️  [延迟统计] LLM 首 Token (TTFT): {ttft_ms:.2f}ms")
        self._notify("llm_first_token")
    
    def record_llm_complete(self) -> None:
        """记录 LLM 完成时间"""
        self._metrics.llm_complete_time = time.perf_counter()
        total_ms = self._metrics.get_llm_complete_ms()
        logger.info(f"⏱️  [延迟统计] LLM 完成: {total_ms:.2f}ms")
        self._notify("llm_complete")
        self.log_metrics("llm_complete")
    
    def record_tts_started(self) -> None:
        """记录 TTS 开始时间"""
        self._metrics.tts_start_time = time.perf_counter()
        logger.info("🎵 TTS 开始播放")
        self._notify("tts_started")
        self.log_metrics("tts_started")
    
    def get_metrics_snapshot(self) -> LatencyMetrics:
        """
        获取当前 metrics 的快照
        
        用于在异步场景下避免数据被新轮次覆盖
        """
        return LatencyMetrics(
            turn_id=self._metrics.turn_id,
            start_time=self._metrics.start_time,
            api_latency_ms=self._metrics.api_latency_ms,
            llm_first_token_time=self._metrics.llm_first_token_time,
            llm_complete_time=self._metrics.llm_complete_time,
            tts_start_time=self._metrics.tts_start_time,
            user_text=self._metrics.user_text,
        )
    
    def log_metrics(self, stage: str = "complete") -> None:
        """
        输出格式化的延迟统计日志
        
        Args:
            stage: 统计阶段，如 "llm_first_token", "llm_complete", "tts_started", "complete"
        """
        m = self._metrics
        if m.start_time == 0:
            return
        
        user_text_preview = m.user_text[:30] if m.user_text else ""
        
        logger.info("")
        logger.info("=" * 70)
        logger.info(f"⏱️  [延迟统计] Turn #{m.turn_id} | Stage: {stage}")
        logger.info(f"📝 用户输入: {user_text_preview}...")
        logger.info("-" * 70)
        logger.info(f"├─ 🌐 API (getChatPrompt):    {m.api_latency_ms:>8.2f} ms")
        logger.info(f"├─ 🚀 LLM TTFT (首token):     {m.get_llm_ttft_ms():>8.2f} ms")
        logger.info(f"├─ 🔊 TTS 启动 (首token后):   {m.get_tts_startup_ms():>8.2f} ms")
        logger.info(f"├─ 🎵 TTS 开始播放 (从开始):  {m.get_tts_start_ms():>8.2f} ms")
        logger.info(f"├─ 📝 LLM 生成耗时:           {m.get_llm_generation_ms():>8.2f} ms")
        logger.info(f"├─ ✅ LLM 完成 (从开始):      {m.get_llm_complete_ms():>8.2f} ms")
        logger.info("-" * 70)
        logger.info(f"└─ 📊 总延迟 (用户输入→TTS):  {m.get_total_latency_ms():>8.2f} ms")
        logger.info("=" * 70)
        logger.info("")
    
    def _notify(self, event: str) -> None:
        """通知所有观察者"""
        for observer in self._observers:
            try:
                observer(event, self._metrics)
            except Exception as e:
                logger.error(f"Observer error: {e}")
