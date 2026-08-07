# Forestar Editor - Web 版（开发调试 / 高级用户自托管入口）
#
# 参考 Open WebUI 的做法：Web 版先行（Docker 一键部署），桌面版为另一分发形态。
# 本镜像仅供开发者与高级用户自托管使用；普通用户请使用桌面版（Forestar Editor.exe）。
#
# 构建与运行（Windows PowerShell）：
#   docker build -t forestar-editor .
#   docker run -d -p 5000:5000 `
#     -v forestar-data:/root/.forestar-editor/data `
#     forestar-editor
#
# 访问 http://127.0.0.1:5000 即可。

FROM python:3.11-slim

# 非交互式运行，避免产生 .pyc 缓存；FORESTAR_HOST=0.0.0.0 让容器外部可访问
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FORESTAR_HOST=0.0.0.0 \
    FORESTAR_PORT=5000

WORKDIR /app

# 先复制依赖清单并安装，充分利用 Docker 层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端代码与前端资源
COPY server/ server/

# 容器内默认监听 0.0.0.0:5000（可通过 FORESTAR_HOST / FORESTAR_PORT 环境变量覆盖）
EXPOSE 5000

CMD ["python", "server/app.py"]
