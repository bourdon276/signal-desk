# 公网部署选择（2026-10-01）

目标是国庆假期结束前得到 HTTPS 演示地址，不购买域名、不超过 ¥200/月。**2026-10-02 已成功部署：https://signal-desk-demo.onrender.com/ 。**

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

## 2026-10-02 实际进度

代码已推送至 bourdon276/signal-desk 的 main 分支。用户已完成 GitHub CLI 授权及 Render 注册。Render 的 Blueprint 页面弹出 Payment Information Required；尝试手动创建 Postgres 也要求 Add credit card to verify your identity。页面说明会临时预授权 $1，不收费。银行卡信息须由用户在 Render 页面自行填写；当前没有服务、数据库或公网地址，未产生已确认的服务费用。

用户随后完成绑卡，并自行创建免费 Postgres `bourdon`（Oregon，PostgreSQL 18，控制台显示 2026-11-01 到期）。为复用该实例，新增 [`render-existing.yaml`](../render-existing.yaml)：仅创建 Oregon 的免费 Web 服务，通过 `fromDatabase` 引用现有数据库。Render 的[官方 Blueprint 文档](https://render.com/docs/blueprint-spec)允许引用同工作区已存在的资源。标准 `render.yaml` 仍用于没有现有数据库的新部署，两种方案择一。

本账号部署页面的 Blueprint Path 已选 `render-existing.yaml`，计划中只出现 `signal-desk-demo` Web 服务；当前等待用户填写至少 10 位私密 `REGISTRATION_CODE` 并提交。不要将邀请码写入 Git。部署成功后查看服务日志：应完成 Alembic 迁移、手动链接导入和 Uvicorn 启动；用控制台实际给出的 URL 打开应用，再记录来源状态和试用结果。

最终用户补齐邀请码并保存部署，2026-10-02 11:40 服务显示 Live，HTTPS 登录首页实际可访问。数据库迁移、20 条手动链接与 15 条 Fed RSS 入库完成；详细成功与失败记录见[部署复盘](retrospectives/05-deployment-user.md)。上述等待和阻塞为过程记录，已解决；外部用户试用与人工 Eval 仍待完成。

不应把 `compose.production.yaml` 与 `render.yaml` 同时用在同一个 Render 服务上。前者是自有主机 + Caddy 的预备方案，后者是无服务器/域名时的一周预览方案。
