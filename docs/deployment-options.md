# 公网部署选择（2026-10-01）

目标是国庆假期结束前得到 HTTPS 演示地址，不购买域名、不超过 ¥200/月。**当前只有配置文件，尚未在任何平台创建服务，也没有公网地址。**

## 本周预览：Render 免费 Web + 免费 Postgres

项目根目录的 [`render.yaml`](../render.yaml) 定义一个 Docker Web 服务和 PostgreSQL。Render [Web 服务文档](https://render.com/docs/web-services)说明服务会获得 `onrender.com` 公网子域名并由平台处理 HTTPS；无需自购域名。公开仓库可用 [Deploy to Render 按钮](https://render.com/docs/deploy-to-render)直接读 Blueprint；此路径不需要授予 Render GitHub 仓库访问权限，但没有自动部署，后续更新须手动触发。首次 Blueprint 创建时需填写私人邀请码，另外两个密钥由平台生成。Web 进程启动时运行 Alembic 迁移，再由后台线程读固定的美联储 RSS；免费实例休眠期间不会同步，唤醒后才恢复。

[Render 免费服务文档](https://render.com/docs/free)列明：免费 Web 空闲会休眠；免费 Postgres 容量 1 GB、创建 30 天后到期，且无备份。因此这套配置仅用于短期演示和真实用户体验，不能作为持续保存个人反馈的长期方案。超过 30 天前必须升级数据库或迁移数据。免费档仍有带宽、构建时长和实例时数限制，应在控制台观察用量。

## 持续运行：Render 付费入门 Web + Postgres

[Render 当前价格页](https://render.com/pricing)列出 512 MB Web 服务约 $7/月、入门 Postgres 约 $6/月，合计名义 $13/月，另有超额流量或构建等可能费用。实际扣款及人民币折算以创建时控制台为准；若预计超过项目 ¥200/月预算就不升级。这条路可避免免费 Web 休眠和数据库 30 天到期，但仍需安排备份与恢复演练。

## 部署前必须具备

1. 将本目录作为 Git 仓库推到用户控制的 GitHub 仓库；`.env` 和真实用户数据保持不入库。
2. 用户登录 Render，打开 `https://render.com/deploy?repo=https://github.com/bourdon276/signal-desk`，审阅 Blueprint。首次创建时填写私密 `REGISTRATION_CODE`；不要在聊天或仓库公开邀请码。若页面另行要求 GitHub App 授权，先检查权限范围。
3. 等待数据库与 Web 服务创建；打开分配的 HTTPS 地址，确认 `/ready` 和页面可访问，再让 1–2 位试用者实际操作。
4. 检查来源状态、注册门槛、数据保留、费用、实际访问速度；把实际结果写进 README 和部署复盘。

不应把 `compose.production.yaml` 与 `render.yaml` 同时用在同一个 Render 服务上。前者是自有主机 + Caddy 的预备方案，后者是无服务器/域名时的一周预览方案。
