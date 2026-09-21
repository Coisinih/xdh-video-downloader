# VidNest 会员与 Stripe 测试指南

## 已实现的支付模式

VidNest 使用服务端创建 Stripe Checkout Session，提供两种价格：

- 一次性购买：默认选中，支付后获得 30 天 VIP。
- 月度订阅：用户勾选自动续费后使用，允许在 Stripe Customer Portal 中取消。

金额、币种和 Price ID 只从后端环境变量读取，前端不能修改金额。会员开通由 Webhook 确认，浏览器跳转页只用于提示，不直接授予权益。

## Stripe Dashboard 配置（Test mode）

1. 登录 Stripe Dashboard，打开右上角 **Test mode**。
2. 在 Product catalog 创建一个 VidNest VIP 产品。
3. 创建两个 Price：
   - CNY 9.90，一次性（One time）。
   - CNY 9.90，按月（Recurring / Monthly）。
4. 将两个 Price ID 分别记录为 `price_...`。
5. 复制 Test secret key（`sk_test_...`），不要写入 Git。

项目根目录 `.env` 示例：

```text
VIDNEST_DATABASE_PATH=/data/vidnest.db
VIDNEST_FRONTEND_URL=http://localhost:8080
VIDNEST_STRIPE_SECRET_KEY=sk_test_你的测试密钥
VIDNEST_STRIPE_ONE_TIME_PRICE_ID=price_一次性价格
VIDNEST_STRIPE_SUBSCRIPTION_PRICE_ID=price_月度价格
VIDNEST_STRIPE_CURRENCY=cny
VIDNEST_STRIPE_AMOUNT_CENTS=990
VIDNEST_SESSION_COOKIE_SECURE=false
```

`VIDNEST_STRIPE_AMOUNT_CENTS=990` 表示 CNY 9.90。后端会核对 Checkout Webhook 中的金额和币种，避免 Stripe Dashboard 配置错误时误开通会员。

## 本地 Webhook（Stripe CLI）

真实 Test mode 支付不能完全离线：浏览器和后端都需要访问 Stripe。没有公网地址时，使用 Stripe CLI 建立本地转发：

```bash
stripe login
stripe listen --forward-to http://localhost:8000/api/v1/billing/webhook
```

命令会打印类似 `whsec_...` 的临时签名密钥。把它加入 `.env`：

```text
VIDNEST_STRIPE_WEBHOOK_SECRET=whsec_本次监听输出的密钥
```

修改 `.env` 后重启后端。`stripe listen` 终端必须保持运行；每次重新启动监听都可能产生新的临时密钥。

如果使用 Docker，Stripe CLI 运行在宿主机上时转发地址通常应为：

```bash
stripe listen --forward-to http://localhost:8000/api/v1/billing/webhook
```

若只暴露了 Nginx 的 8080 端口，也可以转发到：

```bash
stripe listen --forward-to http://localhost:8080/api/v1/billing/webhook
```

## 完整支付验证

1. 启动后端、前端和 Stripe CLI。
2. 打开 `http://localhost:8080`。
3. 注册一个测试账号；密码至少 10 位，并包含大小写字母、数字、符号中的三类。
4. 打开“会员方案”，默认购买一次性 30 天会员，或勾选自动续费测试订阅。
5. 在 Checkout 页面使用 Stripe 测试卡：

```text
卡号：4242 4242 4242 4242
有效期：任意未来日期
CVC：任意三位数字
```

6. 返回 VidNest 后，页面会轮询 `/api/v1/me` 等待 Webhook 确认。
7. 确认 VIP 生效后重新解析视频，应该能看到 4K/8K（前提是来源实际提供这些格式）。
8. 测试“批量下载”、AI 总结、字幕下载、DeepSeek 翻译和客服工单。
9. 订阅用户点击“管理会员与自动续费”，进入 Stripe Portal 后取消自动续费；在当前周期结束前仍保留权益。

## 无外网环境下的验证

完全断网时不能进行真实 Stripe Checkout，但可以运行本地模拟测试，覆盖：

- Stripe Checkout 创建参数和服务端价格选择。
- Checkout 请求幂等键和重复点击防护。
- Webhook 原始请求体验签。
- 重复 Stripe Event ID 去重。
- 支付成功、异步支付失败、订阅更新、取消和退款。
- 金额/币种不匹配时拒绝开通。
- SQLite 事务、会员有效期、每日免费额度和 VIP 门禁。

这些测试不需要 Stripe 密钥，也不会产生真实支付。真实支付仍必须在 Stripe Test mode 中完成一次端到端验证。

## 安全注意事项

- `sk_test_...`、`sk_live_...`、`whsec_...` 只能放在后端环境变量，不能放进 Vue 代码。
- 生产环境必须设置 `VIDNEST_SESSION_COOKIE_SECURE=true` 并使用 HTTPS。
- Webhook 不能通过前端转发或手工 JSON 直接调用；必须保留原始请求体并验签。
- 订单和 Webhook 事件使用数据库唯一约束，Stripe 重试不会重复开通或重复计费。
- Stripe Dashboard 的退款、订阅状态变化最终都通过 Webhook 同步到本地。
