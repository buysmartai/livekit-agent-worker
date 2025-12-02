# ✅ 视频记忆功能已更新：支持摄像头 + 屏幕分享

## 📝 修改内容

### 1. 第 648 行：触发条件
```python
# 修改前：只支持屏幕分享
if self._last_pingback and self._video_frames.get("screen_share"):

# 修改后：支持屏幕分享或摄像头
has_video = self._video_frames.get("screen_share") or self._video_frames.get("camera")
if self._last_pingback and has_video:
```

### 2. 第 463-478 行：处理逻辑
```python
# 修改前：只获取屏幕分享帧
screen_frame = self._video_frames.get("screen_share")
if not screen_frame:
    return

# 修改后：优先屏幕分享，其次摄像头
video_frame = self._video_frames.get("screen_share")
video_source = "screen_share"

if not video_frame:
    video_frame = self._video_frames.get("camera")
    video_source = "camera"

if not video_frame:
    return

logger.info(f"🔄 [并行] 开始处理视频记忆... (来源: {video_source})")
```

## 🎯 工作逻辑

### 优先级
1. **优先使用屏幕分享** - 如果有屏幕分享帧，使用屏幕分享
2. **其次使用摄像头** - 如果没有屏幕分享但有摄像头，使用摄像头
3. **跳过处理** - 如果两者都没有，跳过处理

### 场景支持

| 场景 | 屏幕分享 | 摄像头 | 结果 |
|------|---------|--------|------|
| 场景1 | ✅ | ✅ | 使用屏幕分享 |
| 场景2 | ✅ | ❌ | 使用屏幕分享 |
| 场景3 | ❌ | ✅ | 使用摄像头 |
| 场景4 | ❌ | ❌ | 跳过处理 |

## 📊 日志示例

### 使用屏幕分享时
```
🚀 [并行] 已启动视频记忆处理任务（后台运行，不阻塞对话）
🔄 [并行] 开始处理视频记忆... (来源: screen_share)
[Gemini] 图像数据: size=2695680, pixels=1797120, channels=1
🔍 [Gemini] 开始分析屏幕内容 (1920x936)...
✅ [Gemini] 分析完成: [Text Content]: ...
💾 [并行] 调用 saveGptResult API...
✅ [并行] saveGptResult 成功
✅ [并行] 视频记忆处理完成并已保存
```

### 使用摄像头时
```
🚀 [并行] 已启动视频记忆处理任务（后台运行，不阻塞对话）
🔄 [并行] 开始处理视频记忆... (来源: camera)
[Gemini] 图像数据: size=921600, pixels=307200, channels=3
🔍 [Gemini] 开始分析屏幕内容 (640x480)...
✅ [Gemini] 分析完成: [Text Content]: The image shows...
💾 [并行] 调用 saveGptResult API...
✅ [并行] saveGptResult 成功
✅ [并行] 视频记忆处理完成并已保存
```

### 没有视频时
```
⚠️  [并行] 没有可用的视频帧，跳过处理
```

## ✅ 完成的修改

1. ✅ 支持屏幕分享和摄像头
2. ✅ 优先级：屏幕分享 > 摄像头
3. ✅ 日志显示视频来源
4. ✅ 修复 VideoFrame reshape 错误
5. ✅ 支持多种像素格式（RGB、RGBA、灰度）

## 🚀 测试

现在可以测试以下场景：

### 测试1：仅屏幕分享
1. 开启屏幕分享
2. 说话："你好"
3. 查看日志：应该看到 `(来源: screen_share)`

### 测试2：仅摄像头
1. 关闭屏幕分享
2. 开启摄像头
3. 说话："你好"
4. 查看日志：应该看到 `(来源: camera)`

### 测试3：两者都有
1. 同时开启屏幕分享和摄像头
2. 说话："你好"
3. 查看日志：应该看到 `(来源: screen_share)` （优先屏幕分享）

### 测试4：两者都没有
1. 关闭屏幕分享和摄像头
2. 说话："你好"
3. 查看日志：应该看到 `⚠️  [并行] 没有可用的视频帧，跳过处理`

## 🎉 全部完成！

现在你的视频记忆功能：
- ✅ 支持屏幕分享
- ✅ 支持摄像头
- ✅ 自动选择可用的视频源
- ✅ 并行处理，不阻塞对话
- ✅ 使用 Gemini Flash 2.5 分析
- ✅ 自动保存到后端 API

可以重启 Agent 开始测试了！🚀

