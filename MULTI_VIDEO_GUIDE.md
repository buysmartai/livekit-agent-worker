# 多视频源使用指南

VisionAgent 支持同时处理多个视频源（摄像头和屏幕分享），并可以选择性地将不同源的图片发送到 LLM 进行分析。

## 功能特性

- ✅ 自动检测和区分摄像头与屏幕分享轨道
- ✅ 支持同时接收多个视频源
- ✅ 灵活控制哪些视频源发送到 LLM
- ✅ 支持预设模式快速切换

## 工作原理

### 1. 视频源自动识别

当客户端发布视频轨道时，Agent 会根据 LiveKit 的 `TrackSource` 枚举自动识别：

| LiveKit TrackSource | 内部标识 | 说明 |
|-------------------|---------|------|
| `CAMERA (0)` | `"camera"` | 摄像头画面 |
| `SCREEN_SHARE (2)` | `"screen_share"` | 屏幕分享画面 |

### 2. 视频帧存储

VisionAgent 内部维护一个字典来存储不同源的最新视频帧：

```python
self._video_frames = {
    "camera": None,       # 摄像头轨道的最新帧
    "screen_share": None  # 屏幕分享轨道的最新帧
}
```

### 3. 选择性发送到 LLM

通过 `_active_video_sources` 集合控制哪些源的图片会被发送到 LLM：

```python
self._active_video_sources = {"camera"}  # 默认只发送摄像头
```

## 使用方法

### 方法 1：直接设置活跃视频源

```python
# 只发送摄像头画面
agent.set_active_video_sources(["camera"])

# 只发送屏幕分享画面
agent.set_active_video_sources(["screen_share"])

# 同时发送摄像头和屏幕分享画面
agent.set_active_video_sources(["camera", "screen_share"])

# 不发送任何视频（纯语音对话）
agent.set_active_video_sources([])
```

### 方法 2：使用预设模式

```python
# 一般对话模式（只用摄像头）
agent.set_mode("general", ["camera"])

# 屏幕分析模式（只用屏幕分享）
agent.set_mode("screen_analysis", ["screen_share"])

# 双视图教学模式（摄像头+屏幕）
agent.set_mode("dual_view", ["camera", "screen_share"])

# 演示模式（只看演示者，不看屏幕）
agent.set_mode("presentation", ["camera"])
```

## 客户端集成

### JavaScript/TypeScript 示例

```typescript
import { Room, Track, createLocalVideoTrack, createLocalScreenTracks } from 'livekit-client';

const room = new Room();
await room.connect(url, token);

// 1. 发布摄像头轨道
const cameraTrack = await createLocalVideoTrack({
  resolution: { width: 1280, height: 720 }
});
await room.localParticipant.publishTrack(cameraTrack, {
  source: Track.Source.Camera  // 重要：指定 source 为 Camera
});

// 2. 发布屏幕分享轨道
const screenTracks = await createLocalScreenTracks({
  resolution: { width: 1920, height: 1080 }
});
await room.localParticipant.publishTrack(screenTracks[0], {
  source: Track.Source.ScreenShare  // 重要：指定 source 为 ScreenShare
});
```

### React 示例

```tsx
import { useLocalParticipant, useTracks } from '@livekit/components-react';
import { Track } from 'livekit-client';

function VideoControls() {
  const { localParticipant } = useLocalParticipant();

  const enableCamera = async () => {
    await localParticipant.setCameraEnabled(true);
    // LiveKit 会自动设置 source 为 Track.Source.Camera
  };

  const enableScreenShare = async () => {
    await localParticipant.setScreenShareEnabled(true);
    // LiveKit 会自动设置 source 为 Track.Source.ScreenShare
  };

  return (
    <div>
      <button onClick={enableCamera}>启用摄像头</button>
      <button onClick={enableScreenShare}>共享屏幕</button>
    </div>
  );
}
```

## 应用场景

### 场景 1：远程教学

学生共享屏幕展示作业，老师通过摄像头观察学生反应：

```python
# 在 Agent 初始化后
agent.set_mode("teaching", ["camera", "screen_share"])
```

LLM 可以同时看到：
- 学生的面部表情（通过摄像头）
- 学生的作业内容（通过屏幕分享）

### 场景 2：技术支持

用户共享屏幕展示问题，客服通过分析屏幕内容提供帮助：

```python
agent.set_mode("support", ["screen_share"])
```

LLM 只关注用户的屏幕内容。

### 场景 3：视频会议助手

在会议中记录讨论内容和演示材料：

```python
# 根据场景动态切换
if is_presenting:
    agent.set_active_video_sources(["screen_share"])
else:
    agent.set_active_video_sources(["camera"])
```

### 场景 4：面试辅助

面试官可以看到候选人的摄像头和屏幕分享（代码编写过程）：

```python
agent.set_mode("interview", ["camera", "screen_share"])
```

## 高级用法

### 动态切换视频源

可以通过语音命令或其他触发器动态切换：

```python
class SmartVisionAgent(VisionAgent):
    async def on_user_turn_completed(self, turn_ctx, new_message):
        user_text = new_message.text_content or ""
        
        # 根据用户指令切换视频源
        if "看我的屏幕" in user_text:
            self.set_active_video_sources(["screen_share"])
        elif "看我" in user_text:
            self.set_active_video_sources(["camera"])
        elif "全部看" in user_text:
            self.set_active_video_sources(["camera", "screen_share"])
        
        await super().on_user_turn_completed(turn_ctx, new_message)
```

### 自定义视频采样率

不同视频源可以使用不同的采样率：

```python
# 在 entrypoint 函数中
if source_type == "camera":
    # 摄像头使用较低帧率（节省成本）
    video_sampler = VoiceActivityVideoSampler(
        speaking_fps=0.5,
        silent_fps=0.1
    )
elif source_type == "screen_share":
    # 屏幕分享使用较高帧率（捕捉更多细节）
    video_sampler = VoiceActivityVideoSampler(
        speaking_fps=1.0,
        silent_fps=0.3
    )
```

### 视频帧预处理

在发送到 LLM 前对不同源的图片进行不同处理：

```python
async def on_user_turn_completed(self, turn_ctx, new_message):
    for source_type in self._active_video_sources:
        frame = self._video_frames.get(source_type)
        if frame is not None:
            # 根据源类型使用不同的推理分辨率
            if source_type == "screen_share":
                # 屏幕分享使用更高分辨率
                width, height = 1024, 768
            else:
                # 摄像头使用较低分辨率
                width, height = 512, 512
            
            image_content = llm.ImageContent(
                image=frame,
                inference_width=width,
                inference_height=height,
            )
            # ...
```

## 调试技巧

### 1. 查看日志

启用 DEBUG 日志级别查看详细信息：

```python
logging.basicConfig(level=logging.DEBUG)
```

你会看到类似的日志：

```
订阅到视频轨道: participant=user123, source=CAMERA, type=camera
开始处理 camera 视频流...
已添加 camera 视频帧到 LLM 上下文，分辨率: 1280x720
```

### 2. 检查活跃视频源

```python
logger.info(f"当前活跃视频源: {agent._active_video_sources}")
logger.info(f"可用视频帧: {list(agent._video_frames.keys())}")
```

### 3. 验证客户端 source 设置

在浏览器控制台检查：

```javascript
room.localParticipant.videoTracks.forEach((pub) => {
  console.log('Video track source:', pub.source);
});
```

## 性能和成本优化

### 1. 选择性发送

只在需要时发送视频帧：

```python
# 检测到特定关键词时才启用视频分析
if any(keyword in user_text for keyword in ["看", "显示", "画面", "屏幕"]):
    self.set_active_video_sources(["camera", "screen_share"])
else:
    self.set_active_video_sources([])  # 纯语音对话
```

### 2. 降低分辨率

使用较低的 `inference_width` 和 `inference_height`：

```python
image_content = llm.ImageContent(
    image=frame,
    inference_width=384,   # 降低分辨率
    inference_height=384,
)
```

### 3. 降低采样率

调整 `VoiceActivityVideoSampler` 参数：

```python
video_sampler = VoiceActivityVideoSampler(
    speaking_fps=0.3,  # 降低帧率
    silent_fps=0.1
)
```

## 故障排查

### 问题 1：看不到屏幕分享的画面

**检查点：**
1. 客户端是否正确设置了 `source: Track.Source.ScreenShare`
2. 检查日志确认 Agent 是否检测到 `SCREEN_SHARE` 轨道
3. 确认 `_active_video_sources` 包含 `"screen_share"`

### 问题 2：LLM 收到多个相同的图片

**原因：** 可能是重复添加了图片内容

**解决：** 代码已经包含去重逻辑，检查是否有自定义修改

### 问题 3：视频帧为 None

**检查点：**
1. 确认视频流是否正在运行
2. 检查 `_process_video_track` 任务是否正常启动
3. 查看是否有异常日志

## 总结

通过 VisionAgent 的多视频源支持，你可以：

✅ 同时处理摄像头和屏幕分享
✅ 灵活控制发送到 LLM 的视频源
✅ 根据应用场景优化性能和成本
✅ 提供更丰富的多模态交互体验

如有问题，请查看日志或参考上述调试技巧。

