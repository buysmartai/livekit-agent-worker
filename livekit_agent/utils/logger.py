"""
日志配置模块

提供统一的日志配置和获取方法。
"""

import logging
import sys
from typing import Optional


# 默认日志格式
DEFAULT_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# 模块根 logger 名称
ROOT_LOGGER_NAME = "livekit_agent"


def setup_logger(
    level: int = logging.INFO,
    format: str = DEFAULT_FORMAT,
    stream=sys.stdout,
) -> logging.Logger:
    """
    配置并返回根 logger
    
    Args:
        level: 日志级别
        format: 日志格式
        stream: 输出流
        
    Returns:
        配置好的 logger
    """
    # 配置根 logger
    logging.basicConfig(
        level=level,
        format=format,
        stream=stream,
    )
    
    # 获取模块根 logger
    logger = logging.getLogger(ROOT_LOGGER_NAME)
    logger.setLevel(level)
    
    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    获取 logger
    
    Args:
        name: logger 名称，如果为 None 则返回根 logger
              如果提供名称，将自动添加 ROOT_LOGGER_NAME 前缀
              
    Returns:
        logger 实例
        
    Examples:
        >>> logger = get_logger()  # 返回 "livekit_agent" logger
        >>> logger = get_logger("services")  # 返回 "livekit_agent.services" logger
        >>> logger = get_logger("services.chat_api")  # 返回 "livekit_agent.services.chat_api" logger
    """
    if name is None:
        return logging.getLogger(ROOT_LOGGER_NAME)
    
    # 如果名称已经包含根前缀，直接使用
    if name.startswith(ROOT_LOGGER_NAME):
        return logging.getLogger(name)
    
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")
