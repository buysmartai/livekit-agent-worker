# ✅ 配置完成总结

## 已完成的配置

### 1. 用户信息
```bash
USER_ID=092dc2543618454f9c00fd7a6621826d
AVATAR_ID=80aee5e80c2e482fb1348adaeb19d421
SESSION_ID=default_session
```

### 2. Chat API 配置
```bash
CHAT_API_BASE_URL=https://your-api.com
CHAT_API_KEY=your_api_key_here
```

### 3. API 请求参数
```bash
TIMEZONE=Asia/Shanghai
LANGUAGE=en
MODEL_PROVIDER=vercel
GPT_MODEL=claude-3-7-sonnet-20250219
```

## 🚀 下一步

### 1. 更新 API 地址和密钥

编辑 `.env` 文件，填写你的实际 API 配置：

```bash
# 修改这两行为你的实际值
CHAT_API_BASE_URL=https://your-actual-api.com
CHAT_API_KEY=your_actual_api_key
```

### 2. 安装 httpx（如果还没安装）

```bash
pip install httpx
```

### 3. 运行 Agent

```bash
python agent.py dev
```

## 📊 运行时日志

当用户说话后，你会看到：

```
🔔 VisionAgent.on_user_turn_completed 被调用！
📝 用户输入: 你好
🔄 准备调用 getChatPrompt API...
🌐 调用 getChatPrompt API: https://your-api.com/chat/getChatPrompt
📋 请求参数: userId=092dc2543618454f9c00fd7a6621826d, avatarId=80aee5e80c2e482fb1348adaeb19d421, sessionId=default_session
✅ 获取动态 prompt 成功
💾 保存 pingback 数据，promptId=xxx
🎭 动态更新 system prompt...
✅ System prompt 已动态更新
```

## 📝 API 请求示例

发送到 `/chat/getChatPrompt` 的请求体：

```json
{
  "reqId": "...",
  "timezone": "Asia/Shanghai",
  "appOs": "livekit",
  "appVersion": "1.0.0",
  "userLocalTime": "2025-12-02T...",
  "userId": "092dc2543618454f9c00fd7a6621826d",
  "avatarId": "80aee5e80c2e482fb1348adaeb19d421",
  "chatStatusType": "append",
  "sessionId": "default_session",
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

## ✅ 验证清单

- [x] `.env` 文件已更新
- [x] `USER_ID` = 092dc2543618454f9c00fd7a6621826d
- [x] `AVATAR_ID` = 80aee5e80c2e482fb1348adaeb19d421
- [ ] `CHAT_API_BASE_URL` 需要填写实际值
- [ ] `CHAT_API_KEY` 需要填写实际值
- [ ] 安��� httpx: `pip install httpx`

## 🎯 完成！

你的配置已经准备就绪。只需：
1. 填写实际的 `CHAT_API_BASE_URL` 和 `CHAT_API_KEY`
2. 运行 `python agent.py dev`
3. 开始测试动态 prompt 功能！

