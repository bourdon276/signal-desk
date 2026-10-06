# 个人资讯 Agent

> MVP 开发中。2026-10-02 已部署至 Render，公网首页可访问。已收到首位朋友的体验反馈；人工 Eval、完整操作验收与第二轮体验仍待完成。

## 自动来源与自己的关注

根据首轮体验意见，新增关注已改为对象订阅：A 股证券代码、CS2 战队名称。股票代码精确连接巨潮公告适配器；战队连接 PandaScore fixtures 适配器，`绿龙` 映射为 Team Spirit，关注赛程/进行状态/比分。线上已配置 PandaScore Token；2026-10-06 已部署按战队 ID 查询及采集统计修复（`a71cd10`）。生产同步成功解析 Spirit，收到 101 场赛事、新增入库 98 条，另 3 场因状态不支持跳过；历史列表达到 100 条上限，来源明确显示“部分同步”。登录后信息流展示仍待人工验收，详见[阶段复盘 09](docs/retrospectives/09-pandascore-ingestion.md)。股票公告仍需 CNINFO 凭据和展示许可。游戏官方公告降为历史内容，不再持续同步。

股票正式适配器已准备，**默认关闭，真实股票自动更新仍待数据账号与展示权限**；详见[配置说明](docs/stock-api-setup.md)。战队配置见[CS2 战队来源](docs/team-source-setup.md)。战队来源不等同于战队新闻文章。自动短摘录可能为英文，中文自动摘要尚未实现。[本阶段复盘](docs/retrospectives/08-entity-following.md)记录实现、来源依据、问题与验收缺口。

## 首轮体验后的改版

项目所有者已转述一位朋友的实际体验意见，见[用户反馈迭代复盘](docs/retrospectives/06-beta-iteration.md)。新版使用“阅讯”阅读台界面：管理关注中可添加自己的股票代码或 CS2 战队；卡片直接显示概况；支持持久化已读/未读及“先读三条”。本轮对象订阅实现复盘见[阶段复盘 08](docs/retrospectives/08-entity-following.md)。存量关键词主题仍兼容读取，但不再出现在新增入口。

每个账号最多20个自定义关注。股票按六位证券代码精确匹配；战队按规范化实体 ID 精确匹配。通用关键词只为旧记录保留兼容，不再作为新增关注入口。战队来源仅覆盖赛程和赛果；战队官方新闻、采访和转会仍是来源缺口。当前18条手动样本附经原文核对的短概况、15条RSS使用来源摘要；概况与人工Eval标签是不同的数据，不能据此增加人工标注计数。

新版追加 `topics` 和 `readings` 两张表，启动时执行 Alembic 升级，保留已有用户、关注与反馈。个人关注和阅读记录不进入Git，也不在运行日志中输出。

PandaScore 官方把 CS2 赛程与结果列入 Fixtures 计划，免费档标注 1000 次请求/小时且注册无需绑卡；但其现行服务条款对客户身份和网站展示有约束。阅讯是公开演示，必须先由账号持有人确认条款适用，再配置 Token。步骤见[战队来源配置](docs/team-source-setup.md)。股票接口配置见[巨潮配置说明](docs/stock-api-setup.md)。

**在线演示：[Signal Desk](https://signal-desk-demo.onrender.com/)** · [GitHub 源码](https://github.com/bourdon276/signal-desk)。首次使用点击“创建账号”，填写维护者单独提供的邀请码。免费实例休眠后访问可能需要等待约一分钟。

把股票、伦敦金与电竞资讯放进一个可追溯的信息流，并根据用户反馈调整推荐。本周目标是 10 月 7 日前做出可访问、可演示、可如实写进简历的 MVP；14 天试用等目标见[长期路线](docs/roadmap-long-term.md)。

## 当前范围

- 股票：通鼎互联（002491.SZ）、辉煌科技（002296.SZ）
- 黄金：伦敦金相关资讯；首版不提供实时行情或交易建议
- 电竞：当前优先支持 CS2 战队对象（绿龙 / Team Spirit）；LoL、无畏契约保留历史记录
- 每周 AI 前沿简报与私有阅读源列入后续阶段

## 当前进度

- 已形成[来源矩阵](docs/source_matrix.md)、[用户流程](docs/user_flow.md)、[试用预算](docs/budget.md)、[长期 Eval 协议](docs/eval/protocol.md)和[固定关键词基线](scripts/eval/baseline.py)。
- 已准备[标注模板](data/eval/annotation_template.csv)、[试用者匿名登记表](docs/beta_recruitment.md)与[来源权限跟进清单](docs/source_permissions.md)。
- 本地已迁移数据库，手动收录20条经核对的股票/电竞原文链接、美联储RSS同步15条。手动样本见 [`docs/demo_links.json`](docs/demo_links.json)。线上 PandaScore Token 已配置；本地开发环境与线上环境使用独立凭据。CNINFO 凭据和展示权限仍未配置。
- 已实现个人关注、反馈、撤销、规则排序、React 页面，以及基于 nanobot Tool 接口的受限证据检索。问答目前为不调用模型的证据列表；nanobot 模型循环尚未接入。
- 本周先争取 1–2 位非开发者实际使用。用户表示已有 5 位愿意参与，尚待匿名核实。已生成 [35 条真实链接、70 个待人工判断位置](data/eval/README.md)，但真实人工标注数仍为 0；本周 Eval 目标是至少 30 条真实链接标注。
- 首轮试用的服务器、模型和数据 API 总预算上限为 ¥200/月。

## 本地环境

要求 Python 3.12、[uv](https://docs.astral.sh/uv/) 和 Docker 兼容运行时。在项目目录运行：

```bash
# 如果使用 Colima 作为本机 Docker 运行时，先启动它；Docker Desktop 用户跳过此行。
colima start
uv sync
cp .env.example .env
# 编辑 .env：让 DATABASE_URL 与 POSTGRES_PASSWORD 使用同一条本机口令，并替换 APP_SECRET、ADMIN_TOKEN。
docker compose up -d db
uv run alembic upgrade head
uv run python -m information_agent.ingest_fed
uv run python scripts/import_demo_links.py
cd web && npm ci && npm run build && cd ..
uv run uvicorn information_agent.main:app --reload
```

然后访问 `http://127.0.0.1:8000/`；进程健康检查为 `/health`，数据库就绪检查为 `/ready`，API 文档为 `/docs`。首次注册只需邮箱和至少 10 位密码；公开部署时需邀请码。登录后选择已有关注，或在“管理关注”添加 A 股代码 / CS2 战队对象；阅读卡片概况，可标为已读、提交反馈，并在“最近反馈”中撤销。`/api/ask` 只返回已入库证据，不调用付费模型。本地 PostgreSQL 数据在 Docker 命名卷中。`.env` 口令只用于本机开发，不可复用于公开部署。

多个来源同步也可通过 `uv run python -m information_agent.sync_worker` 每小时运行：美联储 RSS、可选的 PandaScore CS2 赛程与结果、可选巨潮公告。PandaScore Token 未配置时不请求 API；配置后会按战队 ID 筛选赛程，并把每次的解析、匹配、入库和丢弃数量显示在来源状态中；达到接口单页上限会提示可能不完整。CNINFO 需 Token 与许可开关同时启用。Valve News 不再持续同步。若请求失败，已有条目仍可阅读，`/api/sources` 会显示各来源失败、延迟或未配置状态；`/api/coverage` 返回当前用户关注的覆盖说明。手动收录保存标题、时间、原文 URL 与可选的人工核对概况；没有后台批量抓取第三方正文；管理员录入接口为 `POST /api/admin/items`，需要 `X-Admin-Token`。

### 数据流与 Agent 边界

```text
美联储 RSS / PandaScore fixtures / CNINFO（需配置）─→ 来源适配器 ─┐
人工核对原文链接 ──────────────────────────────────────────────┴→ items（PostgreSQL）→ 个人对象关注与反馈排序 → React 信息流
                                       search_items / get_evidence ←┘
                                                  ↓
                                      带原文链接的证据回答
```

用户关注和反馈按账号保存在 PostgreSQL；“没兴趣”隐藏当前卡片并轻度下调相同关注对象，“重复”隐藏相同事件键，撤销后重新计算。工具只读当前用户关注范围内的已入库记录，每次最多取 5 条；外部资讯内容不会成为可执行指令。当前事件键默认由 URL 生成，跨平台同事件去重还需要更多来源和人工事件归并。

管理员可用 `GET /api/admin/runs` 携带 `X-Admin-Token` 查看最近 50 次同步与问答的运行 ID、状态、数量和错误摘要。问答当前不调用模型，模型 token 与费用为 0；这也意味着它只会列出证据，尚不能生成复杂综合分析。

问答支持股票代码、LoL / Valorant 等别名，以及同一问题中的多个关注对象。工具轨迹还记录参数、耗时和结果数量；不会记录用户问题原文或登录凭据。完整设计和面试说明见[工程说明](docs/engineering-notes.md)。

### 评估

首批标注流程见 [Eval 数据说明](data/eval/README.md)。在项目根目录执行 `uv run python scripts/eval/prepare.py` 导出本地已入库的真实链接清单，人工填写 `data/eval/annotation_queue.csv` 后执行 `uv run python scripts/eval/report.py`。报告给出每个关注对象的关键词时间倒序基线和来源标记排序的 `P@5`、覆盖数、重复率及错误 URL；不足 5 个已判候选时写 N/A。当前没有已完成的人工标注，因此没有可报告的效果数字。个性化反馈改善效果须用后续实际用户偏好另评估。

### 开发前端

后端在 8000 端口运行时，另一个终端进入 `web` 目录执行 `npm run dev`，访问 `http://127.0.0.1:5173/`。Vite 把 `/api` 代理到后端。修改前端后执行 `npm run build`，FastAPI 会提供新构建的页面。

### 公开部署准备

已有多阶段 [`Dockerfile`](Dockerfile)、[`compose.production.yaml`](compose.production.yaml) 和 [`Caddyfile`](Caddyfile)。自有主机路径需先准备域名或 HTTPS 入口，设置独立强口令、`APP_SECRET`、`ADMIN_TOKEN`、`REGISTRATION_CODE` 与 `APP_DOMAIN`，再运行 `docker compose -f compose.production.yaml up -d --build`。当前实际部署使用下方 Render 路径；备份恢复与完整试用验收仍待完成。

2026-10-02 11:40（Asia/Shanghai）Render 显示 Live，公网首页实际打开成功。使用 [`render-existing.yaml`](render-existing.yaml) 创建 Oregon 免费 Web 服务，复用用户创建的免费 PostgreSQL 18 数据库 `bourdon`。用户自行完成绑卡验证和私密邀请码配置。此前版本的 Fed RSS、Steam News 与 `/ready` 均曾实际部署观察成功；旧版本股票源保持未配置。[部署限制](docs/deployment-options.md)：Web 会休眠；数据库控制台显示 **2026-11-01 到期**，须此前迁移或升级。

对象关注改版与 PandaScore Token 已部署。2026-10-06 15:42（Asia/Shanghai）采集修复 `a71cd10` 在 Render 显示 Live；公网 `/ready` 返回 ready，`/api/sources` 返回战队解析、101 场返回数据、98 条新增入库等统计。CNINFO 股票自动公告继续受单独授权约束。

[用 Render Blueprint 部署这个公开仓库](https://render.com/deploy?repo=https://github.com/bourdon276/signal-desk)。该链接会先显示待创建的资源与所需私密环境变量；实际公网地址以部署成功后控制台显示为准。

停止本地数据库：

```bash
docker compose down
```

删除本地数据库和其中的数据：

```bash
docker compose down -v
```

本机使用 [Colima](https://github.com/abiosoft/colima) 提供 Docker 兼容容器运行时；启动和停止运行时分别使用 `colima start` 与 `colima stop`。

本地环境回收资源时运行 `docker compose down` 和 `colima stop`。数据库命名卷会保留；只有明确要删除本地数据库时才运行 `docker compose down -v`。

## 技术栈（初始）

- Python 3.12、uv
- nanobot-ai 0.3.5：`search_items` 和 `get_evidence` 已实现为用户限定的 Tool；完整模型循环待接
- FastAPI、Pydantic Settings
- SQLAlchemy、Alembic、PostgreSQL（Docker Compose 本地开发）
- httpx、feedparser
- PandaScore Fixtures API：可选 Token，CS2 赛程与结果
- React、TypeScript、Vite；Caddy 用于预备的 HTTPS 部署

来源适配、用户反馈与记忆、Eval、外部部署等状态以计划和各阶段复盘为准。实现后会把真实部署地址、使用数据、评估结果和局限补进 README。

## 阶段复盘与交付状态

| 小项目 | 复盘 | 当前状态 |
| --- | --- | --- |
| 0 范围与来源门 | [复盘 0](docs/retrospectives/00-scope-eval.md) | 已完成 |
| 1 数据与来源 | [复盘 1](docs/retrospectives/01-ingestion.md) | 实现已交付，场景验收待补 |
| 2 推荐与记忆 | [复盘 2](docs/retrospectives/02-feedback.md) | 实现已交付，场景验收待补 |
| 3 Web 闭环 | [复盘 3](docs/retrospectives/03-web.md) | 构建完成，实际用户和手机验收待补 |
| 4 Agent 与 Eval | [进度复盘 4](docs/retrospectives/04-agent-eval.md) | 工具与报告脚本就绪，人工标注未完成 |
| 5 部署与试用 | [部署复盘](docs/retrospectives/05-deployment-user.md) / [试用步骤](docs/beta-5-minute-guide.md) | 公网部署成功；已有首轮朋友反馈，完整验收待完成 |
| 6 最终交付 | [工程说明](docs/engineering-notes.md) | README 已更新，最终指标和演示待补 |

2026-10-02 已完成 Python Ruff 静态检查、TypeScript/Vite 构建和本地 Docker 镜像构建。尚未运行功能场景验收，不据此声称账号隔离、推荐效果或生产可靠性已通过验证。

### 2026-10-06 后续修复

API 比赛 slug 被错误拼成原文网页，导致 404；已修复展示与引用逻辑，保留旧去重标识。新增 Esports Insider Counter-Strike RSS 战队新闻索引，范围有限，生产状态见[复盘 10](docs/retrospectives/10-links-team-news.md)。

[简历描述与面试准备](docs/resume-agent-project.md)区分已实现的工具编排/反馈记忆与尚未实现的模型自主循环，不提供未经测量的效果指标。

本轮修复 `86af669` 已于 2026-10-06 15:54（北京时间）部署成功。新闻 RSS 生产首次同步读取 10 篇、匹配绿龙 0 篇；来源接通不等于战队新闻覆盖完成。
