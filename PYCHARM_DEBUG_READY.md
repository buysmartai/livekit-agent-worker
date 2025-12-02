# ✅ PyCharm Debug 配置完成

## 🎉 配置已自动完成！

我已经为你创建了 PyCharm 的运行配置文件，现在你可以直接在 PyCharm 中使用。

## 📋 可用的运行配置

### 1. **LiveKit Agent - Dev Mode** （开发模式 - 推荐）
- 参数：`dev`
- 特性：支持热重载（代码修改后自动重启）
- 用途：日常开发和调试

### 2. **LiveKit Agent - Start (Production)** （生产模式）
- 参数：`start`
- 特性：生产环境配置
- 用途：测试生产部署

## 🚀 如何使用

### 方法 1: 直接使用（推荐）

1. **重启 PyCharm** 或者点击 `File → Reload All from Disk`
2. 在 PyCharm 右上角，你会看到运行配置下拉菜单
3. 选择 **"LiveKit Agent - Dev Mode"**
4. 点击 **Debug 按钮（🐛图标）** 或按 `Shift + F9`

### 方法 2: 手动选择配置

1. 点击 PyCharm 右上角的运行配置下拉菜单
2. 选择 **"Edit Configurations..."**
3. 你会看到左侧已经有两个配置：
   - ✅ LiveKit Agent - Dev Mode
   - ✅ LiveKit Agent - Start (Production)
4. 选择其中一个，点击 **OK**
5. 点击 **Debug 按钮**

## 🐛 设置断点进行调试

### 推荐的断点位置

在以下行设置断点来调试 REST API 调用：

1. **第 319 行** - API 调用入口
   ```python
   prompt_result = await self.get_dynamic_prompt(
   ```

2. **第 327 行** - 检查 API 响应
   ```python
   if prompt_result:
   ```

3. **第 337 行** - 检查返回的消息
   ```python
   if api_messages:
   ```

4. **第 247 行** - 进入 get_dynamic_prompt 方法
   ```python
   logger.info(f"🌐 调用 getChatPrompt API...")
   ```

### 如何设置断点

1. 在代码编辑器中，点击想要设置断点的**行号左侧**
2. 出现**红色圆点**表示断点已设置
3. 再次点击可以取消断点

## 📊 调试时查看变量

当程序在断点处暂停时，在 PyCharm 底部的 **Debug 窗口**中：

### Variables 标签
- `user_text`: 用户输入的文本
- `prompt_result`: API 返回的完整结果
- `data`: API 返回的数据部分
- `api_messages`: 返回的消息列表
- `self._last_pingback`: 保存的 pingback 数据

### Console 标签
可以执行表达式查看更多信息：
```python
# 查看完整的 prompt_result
import json
print(json.dumps(prompt_result, indent=2))

# 查看环境变量
import os
print(f"API URL: {os.getenv('CHAT_API_BASE_URL')}")
print(f"User ID: {os.getenv('USER_ID')}")
```

## ⌨️ 调试快捷键

| 快捷键 | 功能 |
|--------|------|
| `F9` | 继续执行（Resume Program） |
| `F8` | 单步执行（Step Over） |
| `F7` | 进入函数内部（Step Into） |
| `Shift + F8` | 跳出函数（Step Out） |
| `Alt + F9` | 运行到光标位置（Run to Cursor） |
| `Ctrl + F8` | 切换断点（Toggle Breakpoint） |
| `Shift + F9` | 开始调试（Debug） |
| `Cmd + F2` | 停止程序（Stop） |

## 🔍 验证配置成功

启动后，你应该在 Debug 控制台看到：

```
Connected to pydev debugger (build 252.27397.106)
2025-12-02 14:30:00 - __main__ - INFO - 启动 LiveKit Agent Worker...
2025-12-02 14:30:00 - asyncio - DEBUG - Using selector: KqueueSelector
2025-12-02 14:30:00 - livekit.agents - DEV - Watching /Users/sunyin/Documents/buysamrtai/livekit-agent-worker
2025-12-02 14:30:01 - livekit.agents - INFO - starting worker
2025-12-02 14:30:01 - livekit.agents - INFO - registered worker
✅ 配置成功！
```

## 🎯 调试 REST API 的完整流程

1. **在第 319 行设置断点**
2. **启动 Debug**（`Shift + F9`）
3. **等待用户说话**
4. **程序会在断点处暂停**
5. **按 F8 单步执行**，观察：
   - `user_text` 变量的值
   - API 请求参数
   - API 响应数据
6. **查看 `prompt_result`**，确认 API 返回正确
7. **继续单步**，观察 system prompt 更新过程
8. **按 F9 继续执行**

## ⚠️ 常见问题

### Q: PyCharm 没有显示新的运行配置
**解决**: 
- 点击 `File → Reload All from Disk`
- 或重启 PyCharm

### Q: Debug 时报错 "No module named 'httpx'"
**解决**: 
```bash
pip install httpx
```

### Q: 断点没有生效
**解决**: 
- 确保使用的是 **Debug**（🐛） 而不是 Run（▶️）
- 检查断点是否是**红色实心圆点**（不是灰色）

### Q: 看不到日志输出
**解决**: 
- 在 Debug 窗口切换到 **Console** 标签
- 或在配置中勾选 "Emulate terminal in output console"

## 🎉 现在可以开始调试了！

1. **选择配置**: LiveKit Agent - Dev Mode
2. **点击 Debug**: 🐛 按钮或按 `Shift + F9`
3. **在关键位置设置断点**
4. **开始调试你的 REST API 集成**

祝调试顺利！🚀

