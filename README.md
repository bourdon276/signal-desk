# 个人资讯 Agent

> 开发中。2026-10-01 起按[一周 MVP 计划](PLAN.md)推进。当前已具备本地可运行原型，尚未公开部署或邀请外部用户。

把股票、伦敦金与电竞资讯放进一个可追溯的信息流，并根据用户反馈调整推荐。本周目标是 10 月 7 日前做出可访问、可演示、可如实写进简历的 MVP；14 天试用等目标见[长期路线](docs/roadmap-long-term.md)。

## 当前范围

- 股票：通鼎互联（002491.SZ）、辉煌科技（002296.SZ）
- 黄金：伦敦金相关资讯；首版不提供实时行情或交易建议
- 电竞：英雄联盟、CS2、无畏契约
- 每周 AI 前沿简报与私有阅读源列入后续阶段

## 一周 MVP 与小项目 0 进度

- 已形成[来源矩阵](docs/source_matrix.md)、[用户流程](docs/user_flow.md)、[试用预算](docs/budget.md)、[长期 Eval 协议](docs/eval/protocol.md)和[固定关键词基线](scripts/eval/baseline.py)。
- 已准备[标注模板](data/eval/annotation_template.csv)、[试用者匿名登记表](docs/beta_recruitment.md)与[来源权限跟进清单](docs/source_permissions.md)。
- 本地已迁移数据库，手动收录 20 条经核对的股票/电竞原文链接，并从美联储货币政策 RSS 同步 15 条。手动样本见 [`docs/demo_links.json`](docs/demo_links.json)。股票和电竞自动接入仍待权限确认。
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

然后访问 `http://127.0.0.1:8000/`；进程健康检查为 `/health`，数据库就绪检查为 `/ready`，API 文档为 `/docs`。首次注册只需邮箱和至少 10 位密码；公开部署时需邀请码。登录后选择关注项，点击卡片反馈并在右侧撤销。`/api/ask` 只返回已入库证据，不调用付费模型。本地 PostgreSQL 数据在 Docker 命名卷中。`.env` 口令只用于本机开发，不可复用于公开部署。

RSS 同步目前也可通过 `uv run python -m information_agent.sync_worker` 每小时运行。只访问固定的美联储 RSS URL；若请求失败，已有条目仍可阅读，`/api/sources` 会显示失败与最后成功时间。手动收录只保存标题、时间和原文 URL，不抓第三方正文；管理员录入接口为 `POST /api/admin/items`，需要 `X-Admin-Token`。

### 开发前端

后端在 8000 端口运行时，另一个终端进入 `web` 目录执行 `npm run dev`，访问 `http://127.0.0.1:5173/`。Vite 把 `/api` 代理到后端。修改前端后执行 `npm run build`，FastAPI 会提供新构建的页面。

### 公开部署准备

已有多阶段 [`Dockerfile`](Dockerfile)、[`compose.production.yaml`](compose.production.yaml) 和 [`Caddyfile`](Caddyfile)。需先准备指向主机的域名或可配置的 HTTPS 入口，设置独立强口令、`APP_SECRET`、`ADMIN_TOKEN`、`REGISTRATION_CODE` 与 `APP_DOMAIN`，再运行 `docker compose -f compose.production.yaml up -d --build`。**当前未执行公网部署**；费用、备份恢复和外部试用结果仍未验证。

用户目前没有服务器或域名。本周首选 [`render.yaml`](render.yaml) 的 Render 免费预览路径，取得平台自带的 HTTPS 子域名；[部署选择与限制](docs/deployment-options.md)列明免费数据库 30 天到期、无备份和 Web 休眠等条件。部署需要用户控制的 Git 仓库与 Render 账号连接，当前尚未进行。

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
- React、TypeScript、Vite；Caddy 用于预备的 HTTPS 部署

来源适配、用户反馈与记忆、Eval、外部部署等状态以计划和各阶段复盘为准。实现后会把真实部署地址、使用数据、评估结果和局限补进 README。
