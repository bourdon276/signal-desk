# 小项目 0：来源矩阵

初稿日期：2026-09-30；状态更新：2026-10-02。这里的“候选”表示已找到入口，不表示已获得自动采集、再分发或商用许可。采集器开发前须再次核对条款、访问方式和授权范围。

已接入[美联储货币政策 RSS](https://www.federalreserve.gov/feeds/press_monetary.xml)，仅作为伦敦金宏观候选，不推断金价。CS2 战队计划采用 PandaScore 公共 fixtures 接口，只提供战队赛程、进行状态和比分；绿龙映射为 Team Spirit。股票正式适配器已准备，但仍等待巨潮账号与展示权限，默认关闭。Valve Steam 新闻保留历史记录，不再作为电竞主要来源。

一周 MVP 的自动接入门槛与手动链接降级方式以[当前计划](../PLAN.md)为准；本表仍覆盖全部六个关注对象。

| 关注对象 | 首选候选 | 补充候选 | 当前接入判断 | 降级方式 |
| --- | --- | --- | --- | --- |
| 任意 A 股代码 | [巨潮资讯](https://www.cninfo.com.cn/)公司公告，交易所披露 | 同花顺 iFinD、东方财富 Choice | 输入六位代码会创建精确的个人股票对象关注；服务端巨潮接口目前仍等待账号与展示许可，未配置时不会自动出现新公告，也不提供实时行情 | 只展示合法取得的公告链接；来源未配置/失败时明确显示，不生成“今日无公告”结论 |
| 伦敦金相关资讯 | [美联储 RSS](https://www.federalreserve.gov/feeds/feeds.htm)货币政策消息、[美国劳工统计局 RSS](https://www.bls.gov/feed/) CPI 等宏观数据 | 后续补充获授权的黄金市场新闻源 | 美联储货币政策 RSS 已按官方聚合器说明接入，仅保留简短摘要和原文链接；BLS 待核。宏观消息仅作候选，不自动断言金价因果 | 仅展示事件原始链接与发布时间；无黄金专门新闻源时明确标记覆盖不足。不提供实时价格或交易建议 |
| 英雄联盟 | [LoL Esports 新闻](https://lolesports.com/news) | [虎扑 LOL 社区](https://bbs.hupu.com/all-lol) | Riot 页面可公开浏览，自动获取/摘要权利待核；虎扑自动获取受用户协议限制，当前禁止接入 | 只保留已授权官方来源；若无获准来源，暂停此对象自动推荐，并显示缺口 |
| 关注的 CS2 战队（本例：绿龙 / Team Spirit） | [PandaScore CS2 fixtures API](https://developers.pandascore.co/reference/get_csgo_matches_upcoming-1) | [Team Spirit 官方 Telegram](https://t.me/team_spirit_official)、[完美世界电竞](https://www.pwesports.cn/)、[虎扑 CS2 社区](https://bbs.hupu.com/csgo) | 已实现免费 fixtures API 适配器；需服务端 Token。仅采集赛程、进行状态和赛果，不是战队新闻文章/采访。官方 Telegram 可人工查看，自动读取方式及展示许可待核；Valve 游戏公告降为低优先级并停止持续同步。套餐以[官方定价](https://www.pandascore.co/pricing)为准 | Token 未配置时关注仍可保存，但没有自动赛程；显示待配置状态。虎扑暂不自动接入；战队官宣暂无自动来源 |
| 无畏契约 | [VALORANT Esports 新闻](https://valorantesports.com/en-GB/news)、[VALORANT 新闻](https://playvalorant.com/en-us/news/) | [虎扑无畏契约社区](https://bbs.hupu.com/803) | Riot 页面可公开浏览，自动获取/摘要权利待核；虎扑当前禁止接入 | 同英雄联盟 |

## 来源准入规则

1. 每个适配器记录来源所有者、原始 URL、采集方式、条款核查日期、允许用途、速率上限和联系人；缺一项则保持“待核”，不启动定时采集。
2. [虎扑用户协议](https://www.hupu.com/policies/user)对未经事先明确书面许可的自动程序获取服务、内容或数据有限制。当前状态为**阻断**；不能以浏览器自动化、换 IP 或让用户粘贴链接后抓正文绕过。若要接入，先取得书面许可并记录范围。
3. 同花顺与东方财富是用户关注的平台，但付费接口权限未确认。首版验收不能依赖其内容。
4. [LBMA Gold Price](https://www.lbma.org.uk/prices-and-data/lbma-gold-price)有单独的数据使用许可要求；实时金价不纳入首版。宏观新闻与金价走势不得混为事实。
5. 来源可以只展示标题、元数据与原始链接的范围，也可以允许摘要、缓存或推送；每个用途分别核查。来源失效时保留故障状态，不能用模型补造消息。

## 小项目 1 之前的决策门

- 核实巨潮/交易所公告可用的正式接口或明确允许的订阅方式，并留存条款链接。
- 核实美联储和劳工统计局 RSS 的可用范围及引用格式。
- 核实 Riot 与完美世界电竞的自动接入和摘要/展示规则；若无法确认，先找获准替代源。
- 虎扑仅在收到书面许可后排入开发，不作为小项目 1 的必交来源。
