# MiniMax STT Plugin for LiveKit Agents

MiniMax 语音识别 (ASR) 插件，用于 LiveKit Agents 框架。

## 安装

```bash
cd livekit-plugins-minimax-stt
pip install -e .
```

## 前置条件

需要 MiniMax API Key，可以通过环境变量设置：

```bash
export MINIMAX_API_KEY="your_api_key_here"
```

## 使用方法

```python
from livekit.plugins.minimax_stt import STT

# 创建 STT 实例
stt = STT(
    api_key="your_api_key",  # 或使用环境变量
    language="zh",
    sample_rate=16000,
)

# 流式识别
stream = stt.stream()
```

## 配置参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `api_key` | str | None | MiniMax API Key，默认从环境变量读取 |
| `model` | str | "speech-01" | ASR 模型名称 |
| `language` | str | "zh" | 识别语言 (zh/en/ja/ko/auto) |
| `sample_rate` | int | 16000 | 音频采样率 |
| `encoding` | str | "pcm" | 音频编码格式 |

## 注意事项

⚠️ **重要**: 此插件需要根据 MiniMax 实际的 ASR API 文档进行配置。
请确认以下信息后更新 `models.py` 中的配置：

1. WebSocket 端点 URL
2. 音频格式要求
3. 认证方式
4. 消息协议格式

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest
```

## License

Apache-2.0
