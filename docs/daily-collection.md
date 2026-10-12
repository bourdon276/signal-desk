# 每日提前采集与首访延迟

## 工作方式

- 网页服务存活时，每小时执行一轮采集。新闻提前写入 Postgres，打开阅读台不等待外部新闻网站。
- GitHub Actions `Prepare daily news` 每天按北京时间 **06:43、13:13、19:43** 唤醒服务并调用固定来源采集接口。它不依赖用户登录。
- 同一服务进程的采集轮次与各来源设有锁；并发最多两路，重复触发不会并行调用同一来源。
- 搜索优先处理没有缓存或缓存最早过期的关注。有效缓存不占用本轮十个任务的位置。采集仍遵守原有日/月搜索额度，不自动增加费用上限。
- 阅读台显示最近采集完成时间和当前列表中今天发布的新闻条数。时间指实际采集/发布时间，不把旧消息改成今天。

## 首次启用

1. 为调度生成至少32字符的随机 `SYNC_TRIGGER_TOKEN`。它只允许触发固定来源采集，不能访问个人关注、反馈、文章或管理接口。
2. Render → Environment 添加 `SYNC_TRIGGER_TOKEN`，保存并部署。
3. GitHub → 仓库 Settings → Secrets and variables → Actions 添加同名 secret，值与 Render 相同。
4. GitHub → Actions → Prepare daily news → Run workflow 执行首次采集。成功后查看任务结果和阅读台时间。

本次维护已生成本地 `data/sync-trigger-token.txt`（权限0600，Git忽略），并配置 GitHub secret；Render 的新凭据仍由维护者填写。不要把密钥提交到仓库或聊天。

接口 `POST /api/admin/sync` 使用 `X-Sync-Token` 请求头。未配置或错误密钥返回403。响应包含各固定来源结果与轮次 run_id，管理员运行记录保存 `scheduled_collection`。本机单轮可用：

```bash
uv run python -m information_agent.sync_worker --once
```

## 不能保证的部分

- GitHub 定时任务可能延迟，长期无仓库活动可能被禁用；这不是严格准点服务。[GitHub 官方说明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- 外部网站、搜索索引、配置授权和日额度决定覆盖。每个用户都有当天新闻必须以当天确实有匹配报道为前提；新关注、来源故障和额度不足不能承诺完整覆盖。
- 定时采集能解决“睡着时没人采集”，不能消除任意时间访问的免费实例启动延迟。Render 免费实例闲置15分钟休眠，再次启动约一分钟。持续快速访问需要常驻实例。[Render 官方说明](https://render.com/docs/free)
- Docker 启动仍执行数据库迁移，但不再每次重导演示链接。演示导入改为明确手动操作。
- 当前锁只适用于一个服务进程，多实例部署需数据库任务锁/独立队列。HTTP超时不等于采集取消，不自动重试变更请求。

## 日常排查

先看阅读台“最近完成”是否为今天，再看 Actions 任务和来源更新。若采集已完成而今天发布数为0，检查所选关注、栏目、时间窗口、反馈隐藏和实际报道发布时间。不要用比赛或旧文章填充新闻列表。
