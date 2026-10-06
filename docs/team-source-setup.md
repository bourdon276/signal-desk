# CS2 战队关注来源配置

页面里的 CS2 战队关注按对象匹配，不是关键词过滤。输入“绿龙”会映射为 Team Spirit；其他输入按 PandaScore 返回的正式战队名称匹配。自动来源提供 CS2 比赛赛程、进行状态、公开比分与赛事名称，不提供战队官方新闻、采访、转会公告或直播内实时数据。

## 免费 fixtures API

[PandaScore 定价页](https://www.pandascore.co/pricing)标明免费 Fixtures 计划包含未来与历史赛程、赛前战队/赛事上下文、每小时 1000 次请求，注册不要求信用卡。CS2 赛程、进行中和已结束的比赛端点均列在[官方计划参考](https://developers.pandascore.co/docs/plan-reference)的 All plans 范围内。用户可在 PandaScore 创建自己的账号并从 Dashboard 生成 Token。

**启用前先由账号持有人阅读 [PandaScore 服务条款](https://www.pandascore.co/terms-and-condition)。**现行条款对 Customer 的描述是专业用户，并限定将数据展示在自己的网站上的用途。阅讯是公开演示项目，个人账号是否适用于这一展示情境，不能仅凭免费套餐说明推断；未确认前保持 `PANDASCORE_TOKEN` 为空，不请求或展示该 API 数据。请由你本人在供应商页面作判断/接受条款，不要把账号授权交给我代办。

## 在 Render 启用

1. 先阅读条款并确认其适用于你的公开演示。若不适用，保持来源关闭。
2. 若确认可用，在 PandaScore 创建自己的账号并复制 API Token。不要把 Token 发到聊天或提交到 Git。
3. 打开 Render 的 `signal-desk-demo` 服务 → **Environment**，添加 `PANDASCORE_TOKEN`，值填入 Token。
4. 保存后等待服务重启；有战队关注时，服务端每小时按关注战队查询：先按正式名称解析 Team ID，再分别读取该队即将开始、进行中和已结束的比赛，并在请求中按战队 ID 和 CS2 标题筛选。新建战队关注也会加入一次即时同步队列。
5. 登录阅讯，添加 `绿龙` 或 `Team Spirit`，在“来源与更新状态”查看同步状态。

Token 只通过 `Authorization: Bearer ...` 请求头发送到 `api.pandascore.co`，不进入浏览器、URL 或采集日志。来源状态会显示最近一轮解析到的战队数、收到的比赛数、可展示比赛数、新增/更新数和被丢弃的记录数；单次列表达到 100 条时会提示结果可能不完整。API 失败会显示失败状态并保留已经收录的赛程/比分。“同步完成”只代表请求与处理流程未报错，不保证供应商已返回目标战队的赛程；请结合数量和关注对象列表确认。

## 限制

- 一个小时轮询一次；免费 Render 服务休眠时不会持续运行。
- 每个 match 记录有 100 条分页上限；查询已按关注战队筛选，若某状态仍返回满 100 条，界面会标记结果可能不完整。
- 比赛赛程和赛果不是战队动态新闻。官方公告、采访、阵容变化仍需找到可授权的公开来源。
- 用户输入的 CS2 战队须能与 PandaScore 官方 API 的正式队名对应；`绿龙` 的 Team Spirit 映射已显式记录。

## 官方来源

- [PandaScore 认证方式](https://developers.pandascore.co/docs/authentication)
- [CS2 即将开始的比赛端点](https://developers.pandascore.co/reference/get_csgo_matches_upcoming-1)
- [套餐与 API 速率](https://www.pandascore.co/pricing)
- [CS2 各端点套餐范围](https://developers.pandascore.co/docs/plan-reference)
- [PandaScore 服务条款](https://www.pandascore.co/terms-and-condition)：公开演示启用前由账号持有人确认适用范围。
- [Team Spirit 官方 Telegram](https://t.me/team_spirit_official)：后续人工/获授权来源候选；当前不自动读取频道页面。
