# VidNest

VidNest 是一个用于保存**公开、无 DRM、无需登录**视频的自托管工具。它封装 [yt-dlp](https://github.com/yt-dlp/yt-dlp)，不修改其源码，也不提供绕过平台保护或下载私密、付费内容的能力。

## 启动

```bash
docker compose up --build
```

访问 `http://localhost:8080`。可通过环境变量配置：`VIDNEST_PORT`、`VIDNEST_ALLOWED_HOSTS`（逗号分隔域名白名单）、`VIDNEST_MAX_FILE_SIZE_MB`、`VIDNEST_MAX_CONCURRENT_DOWNLOADS`。

## 本地开发

后端：`cd backend; python -m venv .venv; .venv\Scripts\pip install -r requirements.txt; .venv\Scripts\uvicorn app.main:app --reload`

前端：`cd frontend; npm install; npm run dev`

详见 [需求文档](docs/requirements.md) 与 [架构文档](docs/architecture.md)。
