#!/usr/bin/env bash
# ==========================================================
# CloudStudio 沙盒 — 雨生编辑器 (Flora Editor) 一键启动脚本
# 自动安装依赖并启动 Flask 全栈服务
#
# 说明：本项目为 Flask 单服务架构（前端页面与 API 同端口），
# 无需 Vite / npm 前端构建步骤，也无需 API 代理转发。
# ==========================================================
set -e

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

APP_NAME="🌱 雨生编辑器 (Flora Editor)"
PORT="${FLORA_PORT:-8000}"

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  ${APP_NAME} — CloudStudio 全栈启动 ${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVER_DIR="$PROJECT_DIR/server"

# Python 命令兼容（部分容器只有 python3）
PY=python
command -v python >/dev/null 2>&1 || PY=python3
PIP_CMD=pip
command -v pip >/dev/null 2>&1 || PIP_CMD="python3 -m pip"

# --------------- 依赖 ---------------
echo -e "${YELLOW}[1/2] 安装后端依赖...${NC}"
$PIP_CMD install -r "$PROJECT_DIR/requirements.txt" -q 2>/dev/null \
  || $PIP_CMD install -r "$PROJECT_DIR/requirements.txt"

# --------------- 启动服务 ---------------
echo -e "${YELLOW}[2/2] 启动 Flora 服务 (端口 ${PORT})...${NC}"
cd "$SERVER_DIR"
$PY cloud_run.py &
APP_PID=$!
echo -e "${GREEN}  服务 PID: $APP_PID${NC}"

# 等待服务就绪
sleep 3

# --------------- 完成 ---------------
echo ""
echo -e "${CYAN}========================================${NC}"
echo -e "${GREEN}  ✅ ${APP_NAME} 已启动！${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""
echo -e "  📡 应用地址:  ${GREEN}http://localhost:${PORT}${NC}"
echo -e "  🩺 健康检查:  ${GREEN}http://localhost:${PORT}/api/health${NC}"
echo ""
echo -e "  ${YELLOW}💡 CloudStudio 会自动检测打开的端口，${NC}"
echo -e "  ${YELLOW}   生成可公开访问的预览链接。${NC}"
echo ""
echo -e "  ${YELLOW}按 Ctrl+C 停止服务${NC}"
echo ""

# 捕获退出信号，清理子进程
cleanup() {
  echo ""
  echo -e "${YELLOW}正在停止服务...${NC}"
  kill $APP_PID 2>/dev/null || true
  wait $APP_PID 2>/dev/null || true
  echo -e "${GREEN}服务已停止。${NC}"
  exit 0
}
trap cleanup SIGINT SIGTERM

# 保持前台运行
wait
