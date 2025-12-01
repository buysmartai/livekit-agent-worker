# 更新日志

## 2024-12-02 - 添加视觉分析功能支持

### ✨ 新增功能

- **多模态视觉分析**: 支持同时处理摄像头和屏幕分享的视频画面
- **多视频源支持**: 可以灵活配置使用哪些视频源（摄像头、屏幕分享或两者）
- **自定义 VisionAgent**: 扩展了 Agent 类，支持视频帧管理和动态模式切换

### 🔧 修复

- **添加图像处理依赖**: 在 `requirements.txt` 中添加 `livekit-agents[images]` 扩展
  - 修复了 `ImportError: You haven't included the 'images' optional dependencies` 错误
  - 安装 Pillow (PIL) 库用于视频帧的图像编码

### 📝 文档更新

- **README.md**: 
  - 添加视觉分析功能说明
  - 详细解释为什么需要 `images` 扩展
  - 添加依赖包的详细说明和作用
  - 添加视觉分析功能的配置指南和使用示例
  - 添加常见错误的解决方法

### 🗑️ 移除

- **RAG 功能**: 临时移除了 RAG（检索增强生成）相关逻辑
  - 设置 `_enable_rag = False`
  - 删除了 `inject_context_to_chat` 方法
  - 保留了恢复功能的注释说明

### 📦 依赖变更

**requirements.txt**:
```diff
- livekit-agents[elevenlabs]>=1.2.9
+ livekit-agents[elevenlabs,images]>=1.2.9
```

### 🔍 技术细节

#### 图像处理流程

1. **视频帧捕获**: `_process_video_track` 持续从 LiveKit 轨道读取视频帧
2. **帧存储**: 最新帧存储在 `VisionAgent._video_frames` 字典中
3. **图像编码**: 使用 Pillow 将 `rtc.VideoFrame` 编码为 JPEG/PNG
4. **Base64 转换**: 编码后的图像转为 base64 字符串
5. **发送到 LLM**: 在 `on_user_turn_completed` 钩子中将图像添加到消息

#### 为什么需要 Pillow？

- LiveKit 的 `VideoFrame` 是原始视频数据（YUV/RGB 格式）
- Qwen-VL 模型需要 base64 编码的 JPEG/PNG 图像
- Pillow 负责格式转换和编码工作
- 如果缺少 Pillow，`livekit.agents.utils.images.encode()` 会抛出 ImportError

### 🚀 使用示例

```python
# 配置使用视觉模型
llm=aliyun.LLM(
    model="qwen-vl-max",  # 支持图像输入的模型
)

# 配置视频采样器
video_sampler=VoiceActivityVideoSampler(
    speaking_fps=1.0,   # 说话时 1fps
    silent_fps=0.3      # 沉默时 0.3fps
)
```

### 🐛 常见问题

**Q: 运行时出现 `ImportError: You haven't included the 'images' optional dependencies`**

A: 运行以下命令安装图像处理依赖：
```bash
pip install "livekit-agents[images]>=1.2.9"
```

**Q: 如何验证 Pillow 是否正确安装？**

A: 运行以下命令：
```bash
python -c "from PIL import Image; print('✅ PIL installed successfully')"
```

**Q: 如何只使用摄像头或屏幕分享？**

A: 在代码中配置：
```python
# 只使用摄像头
agent.set_active_video_sources(["camera"])

# 只使用屏幕分享
agent.set_active_video_sources(["screen_share"])
```

### 📊 性能优化

- 默认配置：摄像头 + 屏幕分享同时启用
- 视频采样率：说话时 1fps，沉默时 0.3fps
- 图像分辨率：512x512（可在 `ImageContent` 中配置）

### 🔮 未来计划

- [ ] 恢复 RAG 功能（可选）
- [ ] 添加更多视频源类型支持
- [ ] 优化图像编码性能
- [ ] 添加视频帧缓存机制

