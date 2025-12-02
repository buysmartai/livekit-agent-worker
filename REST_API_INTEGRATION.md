# REST API 集成完成说明

## ✅ 已完成的功能

### 1. HTTP 客户端集成
- ✅ 导入 `httpx` 库（异步 HTTP 客户端）
- ✅ 在 `VisionAgent.__init__` 中初始化 `httpx.AsyncClient`
- ✅ 配置连接池和超时（10秒总超时，3秒连接超时）

### 2. 动态 Prompt API 调用
- ✅ 实现 `get_dynamic_prompt()` 方法
- ✅ 调用 `/chat/getChatPrompt` 端点
- ✅ 发送完整的请求体（包含 userId, avatarId, sessionId 等）
- ✅ 处理 API 响应和错误

### 3. System Prompt 动态更新
- ✅ 解析 API 返回的 `messages`
- ✅ 提取 `system` 角色的消息
- ✅ 使用 `update_instructions()` 动态更新 prompt
- ✅ 保存 `pingback` 数据（用于后续 saveGptResult）

### 4. 集成到 `on_user_turn_completed` 钩子
- ✅ 在用户说话后、LLM 调用前触发
- ✅ 调用 REST API 获取动态 prompt
- ✅ 更新 system prompt
- ✅ 继续处理视频帧（多模态）

## 📋 完整流程

```
用户说话: "你好"
  ↓
STT 识别完成
  ↓
on_user_turn_completed 被调用
  ↓
🌐 调用 getChatPrompt API
  ├─ 传入: userId, avatarId, sessionId, userText
  └─ 获取: system prompt, messages, pingback
  ↓
🎭 动态更新 system prompt
  └─ await self.update_instructions(new_system_prompt)
  ↓
📸 添加视频帧（如果有）
  ↓
🤖 发送到 LLM (Qwen-VL-Max)
  ↓
✅ LLM 生成回复
  ↓
🔊 TTS 合成并播放
```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install httpx
```

或更新 `requirements.txt`：
```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 到 `.env`：
```bash
cp .env.example .env
```

编辑 `.env` 文件，填写你的配置：
```bash
# 必需：阿里云 API Key
DASHSCOPE_API_KEY=sk-xxxxx

# 必需：Chat API 配置
CHAT_API_BASE_URL=https://your-api.com
CHAT_API_KEY=your_api_key

# 可选：用户信息（可以动态传入）
USER_ID=user_123
AVATAR_ID=avatar_456
SESSION_ID=session_789
```

### 3. 运行 Agent

```bash
python agent.py dev
```

## 📊 日志输出示例

```
🔔 VisionAgent.on_user_turn_completed 被调用！
📝 用户输入: 你好
🔄 准备调用 getChatPrompt API...
🌐 调用 getChatPrompt API: https://your-api.com/chat/getChatPrompt
📋 请求参数: userId=user_123, avatarId=avatar_456, sessionId=session_789
✅ 获取动态 prompt 成功
💾 保存 pingback 数据，promptId=eb933311ec3e4a1594eadd0e9c1a7a93
📋 API 返回了 2 条消息
🎭 动态更新 system prompt (前100字): 你是 LiveC 系统中的一个角色代理...
✅ System prompt 已动态更新
⚙️  LLM 配置: maxOutputTokens=2000, temperature=0.7
🎥 活跃视频源: {'camera', 'screen_share'}
✅ screen_share 视频帧已捕获: 1920x1080
🖼️  screen_share ImageContent 创建成功
✅ screen_share 图像已添加到消息内容
🚀 最终消息内容包含: 1 个文本, 1 个图像
```

## 🔧 API 请求示例

### 发送到 `/chat/getChatPrompt`

```json
{
  "reqId": "af5b0d71-58c1-435d-82a8-db2a6653a7ea",
  "timezone": "Asia/Shanghai",
  "appOs": "livekit",
  "appVersion": "1.0.0",
  "userLocalTime": "2025-12-02T11:00:00.000",
  "userId": "user_123",
  "avatarId": "avatar_456",
  "chatStatusType": "append",
  "sessionId": "session_789",
  "agentContext": {
    "agentType": "voice_chat",
    "context": {}
  },
  "language": "en",
  "input": null,
  "latestUserInput": [
    {
      "source": "content",
      "type": "text",
      "text": "你好",
      "image_url": null,
      "input_audio": null
    }
  ],
  "timestamp": 1733126400000,
  "modelProvider": "vercel",
  "gptModel": "claude-3-7-sonnet-20250219"
}
```

### 期望的 API 响应

```json
{
  "code": "0",
  "data": {
    "maxOutputTokens": 2000,
    "temperature": 0.7,
    "messages": [
      {
        "role": "system",
        "content": "你是 LiveC 系统中的一个角色代理..."
      },
      {
        "role": "user",
        "content": [
          {
            "type": "text",
            "text": "历史上下文..."
          }
        ]
      }
    ]
  },
  "pingback": {
    "promptId": "eb933311ec3e4a1594eadd0e9c1a7a93",
    "groupId": "a6653ec575314da78c50a1106ea13245",
    "retTimestamp": 1733126400000
  }
}
```

## 🎯 关键特性

### 1. 动态 Prompt 更新
```python
# 在 on_user_turn_completed 中
prompt_result = await self.get_dynamic_prompt(
    user_text=user_text,
    user_id=user_id,
    avatar_id=avatar_id,
    session_id=session_id
)

if prompt_result:
    # 更新 system prompt
    await self.update_instructions(new_system_prompt)
```

### 2. Pingback 数据保存
```python
# 保存 pingback 用于后续调用 saveGptResult
self._last_pingback = prompt_result.get("pingback")
```

### 3. HTTP 客户端复用
```python
# 在 __init__ 中创建，避免重复连接
self._http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(10.0, connect=3.0),
    limits=httpx.Limits(max_keepalive_connections=5)
)
```

## 🔍 调试技巧

### 查看 API 请求详情
设置日志级别为 DEBUG：
```python
logging.basicConfig(level=logging.DEBUG)
```

### 测试 API 连接
```bash
# 使用 httpx 测试
python -c "
import asyncio
import httpx

async def test():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            'https://your-api.com/chat/getChatPrompt',
            json={'test': 'data'}
        )
        print(response.status_code)

asyncio.run(test())
"
```

## ⚠️ 常见问题

### Q1: API 超时
**现象**: 日志显示 `❌ getChatPrompt API 超时（10秒）`

**解决**:
```python
# 增加超时时间
self._http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(30.0, connect=5.0)  # 30秒总超时
)
```

### Q2: 认证失败
**现象**: `❌ API 请求失败: HTTP 401`

**解决**: 检查 `.env` 中的 `CHAT_API_KEY` 是否正确

### Q3: 没有调用 API
**现象**: 没有看到 `🌐 调用 getChatPrompt API` 日志

**原因**: `httpx` 未安装或 `CHAT_API_BASE_URL` 未配置

**解决**:
```bash
pip install httpx
```

## 📝 后续扩展

### 调用 saveGptResult API
在 LLM 生成回复后调用：

```python
async def save_gpt_result(self, assistant_text: str):
    """保存 LLM 生成的结果到后端"""
    if not self._last_pingback:
        return
    
    request_body = {
        "pingback": self._last_pingback,
        "gptResult": assistant_text,
        "timestamp": int(datetime.now().timestamp() * 1000)
    }
    
    await self._http_client.post(
        f"{api_base_url}/chat/saveGptResult",
        json=request_body
    )
```

### 添加重试机制
```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def get_dynamic_prompt_with_retry(self, user_text: str):
    return await self.get_dynamic_prompt(user_text)
```

## ✅ 验证清单

- [x] httpx 已安装
- [x] `.env` 文件已配置
- [x] `CHAT_API_BASE_URL` 指向正确的 API
- [x] `CHAT_API_KEY` 有效
- [x] 日志中可以看到 `🌐 调用 getChatPrompt API`
- [x] System prompt 成功更新
- [x] LLM 使用新的 prompt 生成回复

## 🎉 完成！

你的 LiveKit Agent 现在已经完全支持：
1. ✅ 动态 Prompt 注入
2. ✅ REST API 调用
3. ✅ 多模态视觉分析
4. ✅ 实时对话

运行 `python agent.py dev` 开始测试吧！

