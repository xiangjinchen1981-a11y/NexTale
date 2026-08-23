#!/usr/bin/env bash
# =============================================================================
# 织叙-NexTale 安装脚本
# 功能：创建 Python 虚拟环境、安装依赖、初始化数据库目录、生成启动脚本
# 用法：bash install.sh
# =============================================================================
set -euo pipefail

# 切到脚本所在目录（项目根目录）
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"

# ------------------------- 可配置项 -------------------------
VENV_DIR=".venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"   # 可用 PYTHON_BIN=python3.12 覆盖
PORT="${PORT:-8000}"                  # 默认监听端口，可用 PORT=xxxx 覆盖
HOST="${HOST:-127.0.0.1}"             # 默认只监听本机；对外部署可设 0.0.0.0
# -------------------------------------------------------------

echo "=============================================="
echo "  织叙-NexTale 安装"
echo "=============================================="
echo "项目目录 : $PROJECT_DIR"
echo "Python   : $PYTHON_BIN"
echo "虚拟环境 : $VENV_DIR"
echo "监听地址 : $HOST:$PORT"
echo ""

# ------------------------- 1. 检查 Python -------------------------
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "[错误] 未找到 $PYTHON_BIN，请先安装 Python 3.10+。"
    echo "       macOS:  brew install python"
    echo "       Ubuntu: sudo apt install python3 python3-venv python3-pip"
    exit 1
fi

PY_VER=$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$("$PYTHON_BIN" -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$("$PYTHON_BIN" -c 'import sys; print(sys.version_info.minor)')
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    echo "[错误] 需要 Python 3.10 及以上版本，当前为 $PY_VER。"
    exit 1
fi
echo "[1/5] Python $PY_VER 版本检查通过"

# ------------------------- 2. 创建虚拟环境 -------------------------
echo "[2/5] 创建虚拟环境 $VENV_DIR ..."
if [ ! -d "$VENV_DIR" ]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
else
    echo "      虚拟环境已存在，跳过创建"
fi

# 定位虚拟环境内的 python / pip
if [ -f "$VENV_DIR/bin/python" ]; then
    VENV_PY="$VENV_DIR/bin/python"
    VENV_PIP="$VENV_DIR/bin/pip"
elif [ -f "$VENV_DIR/Scripts/python.exe" ]; then
    # Windows (Git Bash)
    VENV_PY="$VENV_DIR/Scripts/python.exe"
    VENV_PIP="$VENV_DIR/Scripts/pip.exe"
else
    echo "[错误] 虚拟环境创建失败，未找到 python 解释器。"
    exit 1
fi

# ------------------------- 3. 安装依赖 -------------------------
echo "[3/5] 升级 pip 并安装依赖 ..."
"$VENV_PY" -m pip install --upgrade pip
if [ -f "requirements.txt" ]; then
    "$VENV_PY" -m pip install -r requirements.txt
else
    echo "[错误] 缺少 requirements.txt 文件。"
    exit 1
fi

# ------------------------- 4. 初始化数据库 -------------------------
echo "[4/5] 初始化数据库 ..."
# 数据目录（data/uploads/output）会在 storage.py 导入时自动创建；
# 这里显式创建目录并触发建表，确保首次运行前数据库就绪。
mkdir -p data uploads output

# 触发建表：storage 模块导入时执行 _init_db()，自动创建 data/novel.db 及所有表
"$VENV_PY" -c "import storage; storage._init_db(); print('数据库初始化完成: data/novel.db')"

# ------------------------- 5. 生成启动脚本 -------------------------
echo "[5/5] 生成启动脚本 ..."
cat > run.sh <<EOF
#!/usr/bin/env bash
# 织叙-NexTale 启动脚本（由 install.sh 生成）
cd "\$(dirname "\$0")"
exec .venv/bin/uvicorn app:app --host ${HOST} --port ${PORT} "\$@"
EOF
chmod +x run.sh

# 兼容旧 start.sh（若存在则同步指向新环境）
if [ -f "start.sh" ]; then
    cat > start.sh <<EOF
#!/usr/bin/env bash
# 织叙-NexTale 启动脚本
cd "\$(dirname "\$0")"
exec .venv/bin/uvicorn app:app --host ${HOST} --port ${PORT} "\$@"
EOF
    chmod +x start.sh
fi

echo ""
echo "=============================================="
echo "  安装完成！"
echo "=============================================="
echo "启动服务：  ./run.sh"
echo "访问地址：  http://${HOST}:${PORT}"
echo ""
echo "常用参数："
echo "  PORT=9000 HOST=0.0.0.0 bash install.sh   # 自定义端口 / 对外监听"
echo "  ./run.sh --reload                        # 开发模式（热重载）"
echo "=============================================="
