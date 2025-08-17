# --- STAGE 1: Builder ---
# 使用一个完整的、非 slim 的 Python 3.12 镜像作为"构建器"
FROM python:3.12 as builder

# 设置工作目录
WORKDIR /app

# [可选] 如果遇到编译错误，可以取消注释下一行来安装常见的构建依赖
# RUN apt-get update && apt-get install -y build-essential libpq-dev

# 复制 requirements.txt 并构建所有依赖的 wheel 文件
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /app/wheels -r requirements.txt


# --- STAGE 2: Final Image ---
# 使用一个非常轻量的 slim Python 3.12 镜像作为最终的生产镜像
FROM python:3.12-slim

# 清理 apt 缓存
RUN apt-get update && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 从“构建器”阶段复制已安装的依赖
COPY --from=builder /app/wheels /app/wheels
COPY requirements.txt .

# 使用复制过来的 wheels 安装依赖，然后清理掉 wheel 文件
RUN pip install --no-cache-dir --no-index --find-links=/app/wheels -r requirements.txt \
    && rm -rf /app/wheels

# 复制应用代码
COPY . .

# 暴露端口
EXPOSE 8443

# 设置启动命令
CMD ["python", "-u", "main.py"]