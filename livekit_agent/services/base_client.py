"""
HTTP 客户端基类

提供统一的 HTTP 请求处理、错误处理和日志记录。
"""

from abc import ABC
from typing import Optional, Tuple, Dict, Any
import time
import os

try:
    import httpx
except ImportError:
    httpx = None

from ..config import APIConfig
from ..utils.logger import get_logger

logger = get_logger("services.base_client")


class BaseAPIClient(ABC):
    """HTTP API 客户端基类"""
    
    def __init__(self, config: APIConfig):
        """
        初始化 HTTP 客户端
        
        Args:
            config: API 配置
        """
        self._config = config
        self._client = None  # httpx.AsyncClient
        
        if httpx is None:
            logger.error("❌ httpx 未安装，HTTP 功能不可用")
            return
        
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(config.timeout, connect=3.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )
        logger.info(f"✅ HTTP 客户端已初始化: {config.base_url}")
    
    @property
    def is_available(self) -> bool:
        """检查客户端是否可用"""
        return self._client is not None and self._config.is_valid
    
    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[dict] = None,
        timeout: Optional[float] = None,
    ) -> Tuple[Optional[dict], float]:
        """
        发送 HTTP 请求
        
        Args:
            method: HTTP 方法 ("GET", "POST" 等)
            endpoint: API 端点（不含 base_url）
            data: 请求体数据
            timeout: 超时时间（覆盖默认值）
            
        Returns:
            (响应数据, 耗时毫秒) 元组，失败时响应数据为 None
        """
        if not self.is_available:
            logger.error("❌ HTTP 客户端不可用")
            return None, 0.0
        
        start_time = time.perf_counter()
        url = f"{self._config.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        
        try:
            response = await self._client.request(
                method=method,
                url=url,
                json=data,
                headers={
                    "Authorization": f"Bearer {self._config.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=timeout,
            )
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            
            if response.status_code == 200:
                try:
                    result = response.json()
                    return result, elapsed_ms
                except Exception as json_err:
                    logger.error(f"❌ JSON 解析失败: {json_err}")
                    logger.error(f"响应内容: {response.text[:500]}")
                    return None, elapsed_ms
            else:
                logger.error(f"❌ HTTP {response.status_code}: {url}")
                logger.error(f"响应内容: {response.text[:200]}")
                return None, elapsed_ms
                
        except httpx.TimeoutException:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"❌ 请求超时 ({elapsed_ms:.2f}ms): {url}")
            return None, elapsed_ms
            
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"❌ 请求异常 ({elapsed_ms:.2f}ms): {e}")
            return None, elapsed_ms
    
    def _build_common_request_body(self, **kwargs) -> dict:
        """
        构建通用请求体
        
        包含公共字段：reqId, timezone, appOs, appVersion, userLocalTime, timestamp
        """
        from datetime import datetime
        
        body = {
            "reqId": os.urandom(16).hex(),
            "timezone": kwargs.get("timezone", os.getenv("TIMEZONE", "Asia/Shanghai")),
            "appOs": "livekit",
            "appVersion": "1.0.0",
            "userLocalTime": datetime.now().isoformat(),
            "timestamp": int(datetime.now().timestamp() * 1000),
        }
        body.update(kwargs)
        return body
