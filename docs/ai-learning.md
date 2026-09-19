# AI 视频学习助手

AI 能力与现有下载能力隔离在 `/api/v1/ai` 路由下。它仅读取公开视频的已有字幕，不下载音频、不执行 ASR，也不保存账号或长期历史。

## 配置

在部署环境配置：

```text
VIDNEST_DEEPSEEK_API_KEY=你的 DeepSeek Key
VIDNEST_DEEPSEEK_BASE_URL=https://api.deepseek.com
VIDNEST_DEEPSEEK_MODEL=deepseek-flash
```

模型默认值为 `deepseek-flash`。Key 未配置时，下载和解析仍可用；只有 AI 总结会返回“尚未配置 DeepSeek API Key”。

## 使用边界

- 优先使用中文字幕，再使用原语言字幕；
- 没有可用字幕的视频不能生成 AI 总结，但可以照常下载；
- 总结、字幕和问答仅保存在内存，默认 2 小时后清理；
- 思维导图以 Mermaid 和可折叠树形大纲展示；
- 问答只根据当前任务的字幕和总结回答，并返回可核验的字幕时间范围。

## 本次交付记录（2026-09-19）

- 新增独立的 `/api/v1/ai` 视频学习路由：字幕轨道、转录、AI 总结、思维导图与基于字幕证据的问答。
- Bilibili 字幕新增 `x/v2/dm/view` 公开元数据兜底，优先选择中文人工字幕；已对 `BV1mAAmzqEfP` 验证得到 114 条字幕。
- DeepSeek 使用 `deepseek-flash`，服务端从项目根目录 `.env` 读取 `VIDNEST_DEEPSEEK_API_KEY`；结构化请求关闭 thinking 模式以保留 JSON 输出预算。
- AI 总结新增 SSE 实时增量输出；前端在生成过程中实时显示 Markdown 内容。
- 思维导图使用 Markmap 渲染：后端将结构化导图转换为层级 Markdown，前端使用 `markmap-lib` 与 `markmap-view` 生成可缩放图形。
- 问答响应对模型返回的引用数量进行契约限制，并保留字幕时间戳引用兜底。

## 验证命令

```text
cd backend && python -m pytest tests -q
cd frontend && npm run test -- --run
cd frontend && npm run build
```

## 字幕与思维导图导出

字幕页支持将当前轨道下载为 UTF-8 `SRT` 或 `TXT`。SRT 使用标准的
`HH:MM:SS,mmm` 时间戳，文件名会根据视频标题、语言和格式生成，并通过
`Content-Disposition` 的 UTF-8 文件名参数交付。

思维导图页支持缩放和拖动、全屏查看、复制 Mermaid、下载 SVG，以及下载高清
PNG。图表加载失败时仍保留结构化大纲作为降级内容；全屏弹窗支持 Esc 关闭并
恢复触发按钮焦点。

视频格式列表由 `backend/app/ytdlp.py` 统一筛选为 1080P、720P、480P、360P，
每个分辨率只保留一个候选，优先 MP4、带音频和较高码率的媒体流。
