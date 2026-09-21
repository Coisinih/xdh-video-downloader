# VidNest 方案设计

## 组件
Vue 3/Vite 前端由 Nginx 托管，并将 `/api` 反代给 FastAPI。FastAPI 使用参数数组调用固定版本的 `yt-dlp`，`ffmpeg` 仅用于合法的格式合并。临时任务、解析结果和交付令牌保存在内存；账号、会话、订单、会员、配额和 Stripe Webhook 账本保存在 SQLite，数据库与下载文件位于容器卷。

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
| `POST /api/v1/auth/register` / `login` | 邮箱密码注册登录，建立 HttpOnly 会话。 |
| `GET /api/v1/me` | 返回当前账号、会员状态和免费额度。 |
| `POST /api/v1/billing/checkout` | 创建一次性或订阅 Stripe Checkout Session。 |
| `POST /api/v1/billing/webhook` | 验签并幂等处理支付、订阅与退款事件。 |
| `POST /api/v1/batch-downloads` | VIP 批量创建下载任务。 |

`POST /api/v1/inspections` 除原有标题、封面、时长和格式外，还会返回可选的
`author`、`description`、`platform` 与 `view_count`。AI 总结任务响应会返回
`stream_text`，它是 SSE 视频大纲的唯一内容来源；结构化总结结果仍用于思维导图和问答。

## 限制与安全
URL 仅限 HTTP/S，DNS 解析后必须为全球公网 IP；格式 ID 必须来自该 inspection。执行命令不用 shell；并发、文件大小和允许主机通过环境变量限制。密码使用 Argon2id；会话 Cookie 为 HttpOnly + SameSite，写操作使用 CSRF Token。Stripe Webhook 使用原始请求体验签、事件 ID 唯一约束和金额/币种复核。临时记录与文件 2 小时清理，日志不得包含媒体直链、支付密钥或会话令牌。
