# VidNest SEO / GEO 实施说明

## 技术方案

首页采用单页 SSG（Static Site Generation）。生产构建由 `vite-ssg` 在构建阶段把 Vue 首页预渲染为完整 HTML，再由现有 Nginx 静态部署。浏览器加载后继续进行 Vue hydration，因此视频解析、下载和 AI 学习工作区的交互方式保持不变。

选择 SSG 而非持续运行 SSR 服务的原因：当前可索引内容集中在首页，内容更新依赖发版，不需要按请求动态渲染；SSG 可以让搜索引擎和 AI 抓取器直接获得完整正文，同时不增加生产环境 Node.js 服务。

## 首页 TDK

| 字段 | 当前规则 |
| --- | --- |
| 页面 | 首页 `/` |
| Title | `VidNest - 万能视频下载总结器 | 在线下载、字幕与 AI 视频总结` |
| Description | 覆盖公开视频下载、清晰度、字幕提取、AI 视频总结、已验证平台和合规边界 |
| Keywords | VidNest、视频下载器、万能视频下载、B站视频下载、AcFun视频下载、虎牙视频下载、AI视频总结、字幕提取、视频学习助手、在线视频解析 |
| Canonical | `https://example.com/`（占位） |
| 更新责任 | VidNest 开发者 |
| 最近更新 | 2026-09-20 |

## 已实现项目

- 唯一 Title、Description、Keywords、Canonical 和 Robots Meta。
- Open Graph 与 Twitter Card，含 1200×630 PNG 分享图。
- `WebSite`、`WebApplication`、`Person` 和 `FAQPage` JSON-LD。
- 首页唯一 H1，以及连续的 H2/H3 内容层级。
- 可见的产品定义、核心功能、使用步骤、平台验证、事实表、合规说明、FAQ 和开发者联系方式。
- `robots.txt`、`sitemap.xml`、`favicon.svg` 和 Web App Manifest。
- `llms.txt` 与 `llms-full.txt`，向 AI 系统提供简洁、可核验的产品上下文和禁止推断项。
- Nginx 文本压缩、哈希静态资源长期缓存和首页 no-cache 策略。
- 键盘跳转链接、FAQ 焦点状态、响应式布局和 reduced-motion 支持。

## 上线前必须替换

`https://example.com` 目前只是占位域名。确定正式域名后，需要全局替换以下文件中的域名：

- `frontend/index.html`
- `frontend/public/robots.txt`
- `frontend/public/sitemap.xml`
- `frontend/public/llms.txt`
- `frontend/public/llms-full.txt`

替换后重新执行生产构建，确保 Canonical、Open Graph URL、JSON-LD、Sitemap 和 AI 可读文档全部使用同一个 HTTPS 规范域名。

## 上线后外部操作

1. 将 `sitemap.xml` 提交至 Google Search Console、Bing Webmaster Tools、百度搜索资源平台、360 站长平台和搜狗资源平台。
2. 使用 Google Rich Results Test 或 Schema.org Validator 验证线上 JSON-LD。
3. 使用 PageSpeed Insights 分别检查移动端和桌面端 Core Web Vitals。
4. 在各搜索平台请求抓取首页，并监控索引、搜索词和抓取错误。
5. 当平台支持状态或产品能力变化时，同步更新首页、JSON-LD、`llms.txt`、`llms-full.txt` 和 Sitemap 的 `lastmod`。

## 本次验证记录

验证日期：2026-09-20。

- `cd frontend && npm test -- --run`：5 项前端测试全部通过。
- `cd frontend && npm run build`：客户端构建、服务端渲染构建和首页 SSG 预渲染全部成功。
- 生成的 `dist/index.html` 包含完整首页正文，而不是只有 Vue 挂载节点。
- 预渲染 HTML 中有且仅有一个 H1，并包含 8 个 H2 内容章节。
- Description、Canonical 和 JSON-LD 均只生成一份；JSON-LD 共包含 4 个图谱实体。
- `sitemap.xml` 已通过 XML 解析，`site.webmanifest` 已通过 JSON 解析。
- `robots.txt`、`sitemap.xml`、`llms.txt`、`llms-full.txt` 和 1200×630 分享图均复制至生产构建目录。
- 使用 Nginx Alpine 镜像执行 `nginx -t`，配置语法检查成功。
- 使用 Chromium 内核浏览器检查 1440px 桌面视口和 375px 移动视口，未发现横向溢出或核心内容遮挡。

当前构建仍会提示思维导图相关延迟加载 chunk 大于 500KB。该警告不阻断构建，也不影响首页 SSG 正文输出；后续可单独评估 Markmap/Mermaid 的进一步拆包。

## 边界

SEO 和 GEO 优化只能提高发现、理解和引用概率，不能保证搜索引擎排名或 AI 对话系统必然推荐。内容中不应虚构平台覆盖、用户规模、公司主体、奖项或市场排名。
