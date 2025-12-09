#!/bin/bash
# LiveKit Agent Worker 安装脚本
# 用于设置开发环境

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "🚀 LiveKit Agent Worker 安装脚本"
echo "================================"

# 检查 Python 版本
PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
echo "📦 检测到 Python 版本: $PYTHON_VERSION"

if [[ $(echo "$PYTHON_VERSION < 3.9" | bc -l) -eq 1 ]]; then
    echo "❌ 需要 Python 3.9 或更高版本"
    exit 1
fi

# 创建虚拟环境
VENV_DIR="$PROJECT_ROOT/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "📁 创建虚拟环境: $VENV_DIR"
    python3 -m venv "$VENV_DIR"
else
    echo "✅ 虚拟环境已存在: $VENV_DIR"
fi

# 激活虚拟环境
echo "🔄 激活虚拟环境..."
source "$VENV_DIR/bin/activate"

# 升级 pip
echo "📦 升级 pip..."
pip install --upgrade pip

# 安装依赖
echo "📦 安装项目依赖..."
pip install -r "$PROJECT_ROOT/requirements.txt"

# 确保本地插件正确安装 (命名空间包兼容)
echo "📦 安装本地 MiniMax TTS 插件..."
MINIMAX_TTS_DIR="$PROJECT_ROOT/livekit-plugins-minimax-tts"

# 删除可能存在的 __init__.py 文件 (命名空间包兼容性)
# 官方 livekit 包使用隐式命名空间，需要保持一致
if [ -f "$MINIMAX_TTS_DIR/livekit/__init__.py" ]; then
    echo "🔧 移除命名空间包 __init__.py (兼容性修复)..."
    rm -f "$MINIMAX_TTS_DIR/livekit/__init__.py"
fi
if [ -f "$MINIMAX_TTS_DIR/livekit/plugins/__init__.py" ]; then
    rm -f "$MINIMAX_TTS_DIR/livekit/plugins/__init__.py"
fi

pip install -e "$MINIMAX_TTS_DIR"

# 验证安装
echo ""
echo "🔍 验证安装..."
python -c "from livekit.plugins.minimax_tts import TTS; print('✅ MiniMax TTS 插件安装成功')"
python -c "from livekit_agent.core import entrypoint; print('✅ livekit_agent 模块加载成功')"

echo ""
echo "================================"
echo "✅ 安装完成!"
echo ""
echo "使用方法:"
echo "  1. 激活虚拟环境: source .venv/bin/activate"
echo "  2. 配置环境变量: cp .env.example .env && vim .env"
echo "  3. 启动开发模式: python agent.py dev"
echo ""
