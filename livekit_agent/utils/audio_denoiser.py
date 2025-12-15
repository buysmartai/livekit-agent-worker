"""
音频降噪模块 - 用于过滤远处的声音

使用 noisereduce 库进行频谱降噪处理。
远处的声音通常具有以下特征：
- 较低的信噪比（SNR）
- 更多的混响
- 高频衰减

通过降噪处理，可以部分抑制这些低质量音频信号。
"""

from __future__ import annotations

import numpy as np
from typing import Optional

from .logger import get_logger

logger = get_logger("utils.audio_denoiser")


class AudioDenoiser:
    """
    音频降噪器
    
    使用 noisereduce 进行频谱降噪，适合实时音频处理。
    
    参数说明：
    - prop_decrease: 噪声衰减比例 (0.0-1.0)，值越大降噪越强
    - stationary: 是否假设噪声是平稳的
    - n_fft: FFT 窗口大小，影响频率分辨率
    - hop_length: 跳跃长度，影响时间分辨率
    
    使用示例：
        denoiser = AudioDenoiser(prop_decrease=0.7)
        clean_audio = denoiser.process(noisy_audio, sample_rate=16000)
    """
    
    def __init__(
        self,
        prop_decrease: float = 0.7,
        stationary: bool = True,
        n_fft: int = 512,
        hop_length: int = 128,
    ):
        """
        初始化降噪器
        
        Args:
            prop_decrease: 噪声衰减比例，0.7 表示降低 70% 的噪声能量
            stationary: 是否使用平稳噪声模型（对于实时音频建议 True）
            n_fft: FFT 窗口大小（默认 512，适合 16kHz 音频）
            hop_length: 跳跃长度（默认 128，约 8ms）
        """
        self.prop_decrease = prop_decrease
        self.stationary = stationary
        self.n_fft = n_fft
        self.hop_length = hop_length
        
        self._nr_available = False
        self._nr = None
        
        # 尝试导入 noisereduce
        try:
            import noisereduce as nr
            self._nr = nr
            self._nr_available = True
            logger.info(f"✅ 音频降噪器初始化成功 (prop_decrease={prop_decrease})")
        except ImportError:
            logger.warning("⚠️  noisereduce 未安装，降噪功能将被禁用")
    
    @property
    def is_available(self) -> bool:
        """检查降噪器是否可用"""
        return self._nr_available
    
    def process(
        self,
        audio_data: np.ndarray,
        sample_rate: int = 16000,
    ) -> np.ndarray:
        """
        处理音频数据，应用降噪
        
        Args:
            audio_data: 输入音频数据（numpy 数组，int16 或 float32）
            sample_rate: 采样率（默认 16000Hz，LiveKit 标准）
            
        Returns:
            降噪后的音频数据（与输入格式相同）
        """
        if not self._nr_available:
            return audio_data
        
        if audio_data is None or len(audio_data) == 0:
            return audio_data
        
        try:
            # 记录输入格式
            original_dtype = audio_data.dtype
            
            # 转换为 float32（noisereduce 要求）
            if original_dtype == np.int16:
                audio_float = audio_data.astype(np.float32) / 32768.0
            elif original_dtype == np.float32:
                audio_float = audio_data
            else:
                # 尝试转换其他格式
                audio_float = audio_data.astype(np.float32)
            
            # 应用降噪
            denoised = self._nr.reduce_noise(
                y=audio_float,
                sr=sample_rate,
                prop_decrease=self.prop_decrease,
                stationary=self.stationary,
                n_fft=self.n_fft,
                hop_length=self.hop_length,
            )
            
            # 转换回原始格式
            if original_dtype == np.int16:
                # 裁剪并转换回 int16
                denoised = np.clip(denoised * 32768.0, -32768, 32767).astype(np.int16)
            elif original_dtype != np.float32:
                denoised = denoised.astype(original_dtype)
            
            return denoised
            
        except Exception as e:
            logger.error(f"❌ 降噪处理失败: {e}")
            return audio_data
    
    def process_frame(
        self,
        frame_data: bytes,
        sample_rate: int = 16000,
        num_channels: int = 1,
        samples_per_channel: int = None,
    ) -> bytes:
        """
        处理 LiveKit 音频帧数据
        
        Args:
            frame_data: 原始音频帧数据（bytes，int16 格式）
            sample_rate: 采样率
            num_channels: 通道数
            samples_per_channel: 每通道样本数
            
        Returns:
            降噪后的音频帧数据（bytes）
        """
        if not self._nr_available:
            return frame_data
        
        try:
            # bytes -> numpy array (int16)
            audio_array = np.frombuffer(frame_data, dtype=np.int16)
            
            # 多通道转单通道
            if num_channels > 1:
                audio_array = audio_array.reshape(-1, num_channels).mean(axis=1).astype(np.int16)
            
            # 应用降噪
            denoised = self.process(audio_array, sample_rate)
            
            # 转回 bytes
            return denoised.tobytes()
            
        except Exception as e:
            logger.error(f"❌ 帧数据降噪失败: {e}")
            return frame_data


class AdaptiveDenoiser(AudioDenoiser):
    """
    自适应降噪器
    
    根据音频能量动态调整降噪强度：
    - 低能量音频（可能是远处声音）-> 更强的降噪
    - 高能量音频（可能是近处声音）-> 较弱的降噪
    """
    
    def __init__(
        self,
        min_prop_decrease: float = 0.3,
        max_prop_decrease: float = 0.9,
        energy_threshold_low: float = 0.01,
        energy_threshold_high: float = 0.1,
        **kwargs,
    ):
        """
        初始化自适应降噪器
        
        Args:
            min_prop_decrease: 最小降噪强度（用于高能量音频）
            max_prop_decrease: 最大降噪强度（用于低能量音频）
            energy_threshold_low: 低能量阈值
            energy_threshold_high: 高能量阈值
            **kwargs: 其他 AudioDenoiser 参数
        """
        super().__init__(**kwargs)
        self.min_prop_decrease = min_prop_decrease
        self.max_prop_decrease = max_prop_decrease
        self.energy_threshold_low = energy_threshold_low
        self.energy_threshold_high = energy_threshold_high
        
        logger.info(
            f"✅ 自适应降噪器初始化 "
            f"(prop_decrease: {min_prop_decrease}-{max_prop_decrease})"
        )
    
    def _calculate_energy(self, audio: np.ndarray) -> float:
        """计算音频能量（RMS）"""
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0
        return np.sqrt(np.mean(audio ** 2))
    
    def _adaptive_prop_decrease(self, energy: float) -> float:
        """根据能量计算自适应降噪强度"""
        if energy <= self.energy_threshold_low:
            return self.max_prop_decrease
        elif energy >= self.energy_threshold_high:
            return self.min_prop_decrease
        else:
            # 线性插值
            ratio = (energy - self.energy_threshold_low) / (
                self.energy_threshold_high - self.energy_threshold_low
            )
            return self.max_prop_decrease - ratio * (
                self.max_prop_decrease - self.min_prop_decrease
            )
    
    def process(
        self,
        audio_data: np.ndarray,
        sample_rate: int = 16000,
    ) -> np.ndarray:
        """
        自适应处理音频数据
        """
        if not self._nr_available:
            return audio_data
        
        if audio_data is None or len(audio_data) == 0:
            return audio_data
        
        try:
            # 计算能量
            energy = self._calculate_energy(audio_data)
            
            # 动态调整降噪强度
            adaptive_prop = self._adaptive_prop_decrease(energy)
            
            # 临时更新 prop_decrease
            original_prop = self.prop_decrease
            self.prop_decrease = adaptive_prop
            
            # 调用父类处理
            result = super().process(audio_data, sample_rate)
            
            # 恢复原始值
            self.prop_decrease = original_prop
            
            return result
            
        except Exception as e:
            logger.error(f"❌ 自适应降噪失败: {e}")
            return audio_data


# 便捷函数
def create_denoiser(
    adaptive: bool = False,
    prop_decrease: float = 0.7,
    **kwargs,
) -> AudioDenoiser:
    """
    创建降噪器实例
    
    Args:
        adaptive: 是否使用自适应降噪
        prop_decrease: 降噪强度
        **kwargs: 其他参数
        
    Returns:
        AudioDenoiser 或 AdaptiveDenoiser 实例
    """
    if adaptive:
        return AdaptiveDenoiser(**kwargs)
    else:
        return AudioDenoiser(prop_decrease=prop_decrease, **kwargs)
