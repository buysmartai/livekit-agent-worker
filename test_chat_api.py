#!/usr/bin/env python3
"""
测试 Chat API 连接

用于验证 getChatPrompt API 是否可以正常访问
"""

import asyncio
import os
import sys
from dotenv import load_dotenv

try:
    import httpx
except ImportError:
    print("❌ httpx 未安装，请运行: pip install httpx")
    sys.exit(1)

# 加载环境变量
load_dotenv()

async def test_chat_api():
    """测试 getChatPrompt API"""

    # 获取配置
    api_base_url = os.getenv("CHAT_API_BASE_URL", "")
    api_key = os.getenv("CHAT_API_KEY", "")
    user_id = os.getenv("USER_ID", "default_user")
    avatar_id = os.getenv("AVATAR_ID", "default_avatar")
    session_id = os.getenv("SESSION_ID", "default_session")

    print("=" * 80)
    print("🧪 测试 Chat API 连接")
    print("=" * 80)
    print(f"📡 API URL: {api_base_url}")
    print(f"👤 User ID: {user_id}")
    print(f"🤖 Avatar ID: {avatar_id}")
    print(f"🔑 Session ID: {session_id}")
    print(f"🔐 API Key: {'*' * 20 if api_key else '(未设置)'}")
    print("=" * 80)

    if not api_base_url or api_base_url == "https://your-api.com":
        print("❌ CHAT_API_BASE_URL 未正确配置")
        return False

    # 构建测试请求
    test_request = {
        "reqId": "test-request-001",
        "timezone": "Asia/Shanghai",
        "appOs": "livekit",
        "appVersion": "1.0.0",
        "userLocalTime": "2025-12-02T14:00:00.000",
        "userId": user_id,
        "avatarId": avatar_id,
        "chatStatusType": "append",
        "sessionId": session_id,
        "agentContext": {
            "agentType": "voice_chat",
            "context": {}
        },
        "language": "en",
        "input": None,
        "latestUserInput": [
            {
                "source": "content",
                "type": "text",
                "text": "Hello, this is a test message",
                "image_url": None,
                "input_audio": None
            }
        ],
        "timestamp": 1733126400000,
        "modelProvider": "vercel",
        "gptModel": "claude-3-7-sonnet-20250219"
    }

    print("\n📤 发送测试请求...")
    print(f"   Endpoint: {api_base_url}/chat/getChatPrompt")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{api_base_url}/chat/getChatPrompt",
                json=test_request,
                headers={
                    "Authorization": f"Bearer {api_key}" if api_key else "",
                    "Content-Type": "application/json"
                }
            )

            print(f"\n📥 收到响应")
            print(f"   Status Code: {response.status_code}")

            if response.status_code == 200:
                result = response.json()
                print(f"   Response Code: {result.get('code', 'N/A')}")

                if result.get("code") == "0":
                    print("\n✅ API 连接成功！")

                    # 显示返回数据
                    data = result.get("data", {})
                    pingback = result.get("pingback", {})
                    messages = data.get("messages", [])

                    print(f"\n📊 返回数据:")
                    print(f"   - maxOutputTokens: {data.get('maxOutputTokens', 'N/A')}")
                    print(f"   - temperature: {data.get('temperature', 'N/A')}")
                    print(f"   - messages 数量: {len(messages)}")
                    print(f"   - promptId: {pingback.get('promptId', 'N/A')}")

                    # 显示 system prompt
                    for msg in messages:
                        if msg.get("role") == "system":
                            content = msg.get("content", "")
                            if isinstance(content, str):
                                preview = content[:150] + "..." if len(content) > 150 else content
                            else:
                                preview = str(content)[:150] + "..."
                            print(f"\n📝 System Prompt (前150字):")
                            print(f"   {preview}")
                            break

                    return True
                else:
                    print(f"\n❌ API 返回错误码: {result.get('code')}")
                    print(f"   完整响应: {result}")
                    return False
            else:
                print(f"\n❌ HTTP 请求失败")
                print(f"   响应内容: {response.text[:500]}")
                return False

    except httpx.TimeoutException:
        print("\n❌ 请求超时（30秒）")
        return False
    except Exception as e:
        print(f"\n❌ 发生异常: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("\n🚀 开始测试...\n")
    success = asyncio.run(test_chat_api())

    if success:
        print("\n" + "=" * 80)
        print("🎉 测试通过！你的 Chat API 配置正确")
        print("=" * 80)
        print("\n下一步：运行 `python agent.py dev` 启动 Agent")
        sys.exit(0)
    else:
        print("\n" + "=" * 80)
        print("⚠️  测试失败，请检查配置")
        print("=" * 80)
        print("\n需要检查的配置项：")
        print("1. CHAT_API_BASE_URL 是否正确")
        print("2. CHAT_API_KEY 是否有效（如果需要）")
        print("3. USER_ID 和 AVATAR_ID 是否存在于系统中")
        print("4. 网络连接是否正常")
        sys.exit(1)

