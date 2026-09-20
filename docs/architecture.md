# VidNest 方案设计

## 组件
Vue 3/Vite 前端由 Nginx 托管，并将 `/api` 反代给 FastAPI。FastAPI 使用参数数组调用固定版本的 `yt-dlp`，`ffmpeg` 仅用于合法的格式合并。任务、解析结果和交付令牌均只保存在内存；下载文件位于容器卷。

## 时序
1. 前端请求 `POST /api/v1/inspections`。
2. API 校验 URL、解析 DNS、拦截非公网地址，再以 `yt-dlp --dump-single-json` 获取可用格式与基础元数据；Bilibili 链接会额外查询公开详情接口，作为作者、简介与播放量的降级数据源。
3. 服务代存模式创建后台任务，前端轮询 `GET /api/v1/downloads/{id}`，完成后访问临时交付 URL。
4. 极速模式创建交付令牌；`GET /api/v1/deliveries/{token}` 默认 302 至已解析媒体地址。对需要 Referer、User-Agent 或 Origin 的来源，服务会自动改为安全流式代理；不会携带 Cookie。

## API
| Endpoint | 行为 |
| --- | --- |
| `POST /api/v1/inspections` | 解析公开 URL，返回 `inspectionId`、元数据和格式。 |
| `POST /api/v1/downloads` | 根据已解析的格式创建服务任务或直连令牌。 |
| `GET /api/v1/downloads/{id}` | 返回任务进度、错误和最终交付 URL。 |
| `GET /api/v1/deliveries/{token}` | 文件响应、302 或流式代理。 |
| `GET /api/v1/health` | 健康状态。 |

`POST /api/v1/inspections` 除原有标题、封面、时长和格式外，还会返回可选的
`author`、`description`、`platform` 与 `view_count`。AI 总结任务响应会返回
`stream_text`，它是 SSE 视频大纲的唯一内容来源；结构化总结结果仍用于思维导图和问答。

## 限制与安全
URL 仅限 HTTP/S，DNS 解析后必须为全球公网 IP；格式 ID 必须来自该 inspection。执行命令不用 shell；并发、文件大小和允许主机通过环境变量限制。临时记录与文件 2 小时清理，日志不得包含媒体直链或令牌。
