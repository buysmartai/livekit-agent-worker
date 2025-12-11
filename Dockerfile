# 使用 Python 3.13 slim 镜像
FROM python:3.13-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制并安装本地 MiniMax TTS 插件
COPY livekit-plugins-minimax-tts/ ./livekit-plugins-minimax-tts/
RUN pip install --no-cache-dir ./livekit-plugins-minimax-tts/

# 复制应用代码
COPY agent.py .
COPY livekit_agent/ ./livekit_agent/

# 创建非 root 用户（先创建用户，确保模型下载到正确的缓存目录）
RUN useradd -m -u 1000 livekit && chown -R livekit:livekit /app

# 切换到 livekit 用户
USER livekit

# 设置 Hugging Face 缓存目录到 /app 下（确保模型被保存在镜像中）
ENV HF_HOME=/app/.cache/huggingface

# 下载 Turn Detector 和 Silero 模型
RUN python agent.py download-files

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# 运行应用
CMD ["python", "agent.py", "start"]
