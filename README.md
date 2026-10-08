# 个人资讯 Agent

> MVP 开发中。2026-10-02 已部署至 Render，公网首页可访问。已收到首位朋友的体验反馈；已完成首轮 30 篇真实兴趣标注与离线反馈回放；完整操作验收与第二轮体验仍待完成。

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
- 已实现个人关注、反馈、撤销、规则排序、React 页面，以及基于 nanobot Tool 接口的受限证据检索。已接入受限模型工具循环，默认走确定性证据检索，用户勾选后才调用模型。
- 本周先争取 1–2 位非开发者实际使用。用户表示已有 5 位愿意参与，尚待匿名核实。已完成 [30 篇真实兴趣判断与反馈回放](docs/eval/preference-results-20261008.md)，其中 28 条明确判断、2 条无法判断；新闻事实核验与实体相关性标注仍待完成。
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

用户关注和反馈按账号保存在 PostgreSQL；新增“少看这类”可选同一关注对象下的内容类型、来源或只隐藏本条。“感兴趣”记录已识别内容类型的偏好；无法分类时只影响当前卡片。旧反馈保留对象级权重，“重复”隐藏相同事件键，撤销后重新计算。工具只读当前用户关注范围内的已入库记录，每次最多取 5 条；外部资讯内容不会成为可执行指令。当前事件键默认由 URL 生成，跨平台同事件去重还需要更多来源和人工事件归并。

管理员可用 `GET /api/admin/runs` 携带 `X-Admin-Token` 查看最近 50 次同步与问答的运行 ID、状态、数量和错误摘要。确定性检索不产生模型费用；勾选模型问答后运行受限工具循环，记录 token、估算费用与回退原因。

问答支持股票代码、LoL / Valorant 等别名，以及同一问题中的多个关注对象。工具轨迹还记录参数、耗时和结果数量；不会记录用户问题原文或登录凭据。完整设计和面试说明见[工程说明](docs/engineering-notes.md)。

### 评估

首批标注流程见 [Eval 数据说明](data/eval/README.md)。在项目根目录执行 `uv run python scripts/eval/prepare.py` 导出本地已入库的真实链接清单，人工填写 `data/eval/annotation_queue.csv` 后执行 `uv run python scripts/eval/report.py`。报告给出每个关注对象的关键词时间倒序基线和来源标记排序的 `P@5`、覆盖数、重复率及错误 URL；不足 5 个已判候选时写 N/A。2026-10-08 完成独立的兴趣标注：30 篇、1 位用户，10 条有效反馈用于调整排序、19 篇留出。原始前五明确想看 1 条，反馈后 3 条、另有 1 条无法判断；反馈后精确 P@5 为 N/A，范围 60%–80%，不是线上准确率或统计置信区间。详见 [首轮结果与失败案例](docs/eval/preference-results-20261008.md)。这不替代上面的新闻相关性与事实标签。

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
| 4 Agent 与 Eval | [进度复盘 4](docs/retrospectives/04-agent-eval.md) | 工具与报告脚本就绪，首轮兴趣标注与回放完成；事实评估待完成 |
| 5 部署与试用 | [部署复盘](docs/retrospectives/05-deployment-user.md) / [试用步骤](docs/beta-5-minute-guide.md) | 公网部署成功；已有首轮朋友反馈，完整验收待完成 |
| 6 最终交付 | [工程说明](docs/engineering-notes.md) | README 已更新，最终指标和演示待补 |

2026-10-02 已完成 Python Ruff 静态检查、TypeScript/Vite 构建和本地 Docker 镜像构建。尚未运行功能场景验收，不据此声称账号隔离、推荐效果或生产可靠性已通过验证。

### 2026-10-06 后续修复

API 比赛 slug 被错误拼成原文网页，导致 404；已修复展示与引用逻辑，保留旧去重标识。新增 Esports Insider Counter-Strike RSS 战队新闻索引，范围有限，生产状态见[复盘 10](docs/retrospectives/10-links-team-news.md)。

[简历描述与面试准备](docs/resume-agent-project.md)区分已实现的工具编排/反馈记忆与尚未实现的模型自主循环，不提供未经测量的效果指标。

本轮修复 `86af669` 已于 2026-10-06 15:54（北京时间）部署成功。新闻 RSS 生产首次同步读取 10 篇、匹配绿龙 0 篇；来源接通不等于战队新闻覆盖完成。

## 受限模型 Agent 与 Eval（2026-10-06）

新增模型自主选择检索/证据工具的消息循环，最多 3 轮、6 次只读工具调用；后端绑定用户身份，从已取得证据重建引用。初始版本默认关闭模型；后续已配置供应商并由用户提供真实调用轨迹，见本节末尾。默认问答仍是确定性检索。

勾选模型工具问答后才发送本次问题、关注名称与短证据；失败回退，页面显示回答模式和本人运行轨迹。预算表原子预留月/日额度，默认模型预算 ¥50/月、¥3/日，每用户最多 10 次/日；按配置价格估算，不等于供应商账单。

- [模型配置、边界与验收](docs/model-agent-setup.md)
- [阶段复盘 11](docs/retrospectives/11-model-agent-eval.md)
- 离线回归：`uv run python scripts/eval/agent_regression.py`，使用临时合成数据库和脚本模型，18 个场景已通过。真实模型调用 0，不能当作模型准确率。
- 本地人工标注表：`data/eval/20261006/annotation_queue.csv`，65 条已有文章链接、130 个空白判断，不提交到仓库。这份相关性表仍为空；另有 30 篇兴趣标注，见 [偏好回放报告](docs/eval/preference-results-20261008.md)。
- 报告保留原始前五排序；没有全部标注时 P@5 为 N/A，不过滤未标注候选后计算。

已接入真实模型并完成首轮兴趣标注；仍需至少 10 个真实模型问答案例及新闻事实与相关性评估。报价、事实支持率与偏好效果只按实测填写。

2026-10-06 16:18（北京时间）受限模型与 Eval 版本 `7a14a57` 已部署；重试后健康检查正常。模型接口配置状态为 false，真实模型验收尚待完成。

### 真实模型试用修复

真实通鼎互联调用已由用户提供运行记录：3次模型调用、6次工具、5条证据，估算¥0.01785；未据此声称事实准确率。“最近”默认近7天，今天按上海日期；旧待赛0:0展示已修复。官方DeepSeek使用非思考工具调用模式。私人记录请求明确拒绝，赛事API引用展示来源记录。详见 [复盘12](docs/retrospectives/12-real-model-fixes.md)。

## 细分偏好记忆（2026-10-08，本地待部署）

根据首轮真实兴趣标注暴露的问题，新增内容类型与来源维度，避免把不喜欢版本更新解释为不喜欢整个 CS2 主题。分类使用标题规则，不新增模型费用；偏好按用户与关注对象隔离、限幅、可撤销。旧反馈保持兼容。前端构建和静态检查通过，功能验收与第二批独立效果评估尚未完成。新闻面板匹配为零时提示覆盖不足；本轮未启用新的新闻供应商，绿龙新闻覆盖仍有缺口。详见 [复盘 15](docs/retrospectives/15-preference-granularity.md)。

## 搜索发现路径（本地代码已接入，默认关闭）

固定来源供给不足时，新增可替换的 `SearchProvider`，当前提供 Tavily basic 适配器。它负责发现新闻链接，DeepSeek 继续选择工具和总结。无需现在注册或付费；未配置 Key 时保留已有 RSS、赛事接口和库存检索。

- 支持关注的 A 股和 CS2 战队；固定公开对象搜索词、允许名单域名、近30天日期筛选，URL 去重后进入个人排序。
- 页面可手动搜索单个关注，无需调用模型；模型问答可选库存不足时补搜一次，仍须取得证据后才能引用。
- 同一对象默认共享 6 小时缓存；全站日/月上限 20/600 credits，每用户每日最多 5 次新搜索，失败不假设免费。
- 搜索不默认读取全文，页面明确标记未核验摘录及估计日期。模型原路径最多3轮；允许补搜时最多4轮，工具仍最多6次、问答总超时40秒。
- 新增 Alembic `20261008_04` 迁移。静态检查、前端构建和离线迁移 SQL 生成已完成；尚未执行真实搜索、数据库在线升级或部署本版本，不声称已补齐绿龙新闻。

配置、供应商替换与真实验收步骤见 [搜索说明](docs/search-setup.md)，本轮问题与解决见 [复盘16](docs/retrospectives/16-search-discovery.md)。

### 搜索生产进展

2026-10-08 17:25（北京时间）已部署搜索版本 `1579c38`，线上返回 `search_configured=true`。最近一次全站搜索来源记录为成功：返回5条、匹配3条、新增3条、预留1 credit，2条因对象不匹配过滤。上述“本地、默认关闭、未验证”是实现时状态；当前部署实例已由用户启用 Tavily。该汇总不说明具体对象，绿龙新闻内容、原文链接、缓存和模型补搜仍待登录后验收，不据此宣称新闻覆盖完整。

### 近期消息窗口

默认「新闻」栏目展示近 30 天已收录新闻；PandaScore 比赛记录移至「比赛」栏目，只保留近 30 天记录和未来 7 天赛程。「新闻和比赛」可合并查看。时间与类型在服务端候选截断前过滤，问答工具也受近期窗口约束。历史数据与反馈保留用于审计和兴趣记忆，新闻不足时不会用旧比分填充。

### 自动部署

`render.yaml` 使用 `autoDeployTrigger: commit`，与 Render 控制台的 On Commit 设置一致。推送到服务关联的 main 分支后自动构建上线；以 Render 的 Live 状态及线上版本为准。搜索新闻、添加关注和定时采集无需部署。
