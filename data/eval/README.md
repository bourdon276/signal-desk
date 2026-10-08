# Eval 数据目录

`annotation_template.csv` 是空白模板。运行 `uv run python scripts/eval/prepare.py` 会从本地数据库导出 `items.jsonl` 与 `annotation_queue.csv`，每条分别对所属关注对象和一个容易混淆的其他对象标注；具体数量由导出时的数据库决定。脚本在清单已存在时拒绝覆盖，以免丢失人工标注。生成文件和个人阅读/反馈记录均不提交到 Git。

打开 `annotation_queue.csv`，逐行核对 `canonical_url`，填写：

- `relevance`：有实质新信息填 `1`；无关、纯重复、明显过时或标题党填 `0`。
- `entity_match`：确实属于 `watch_id` 对象填 `1`，否则填 `0`。
- `duplicate_of`：如同事件重复，填主样本 `sample_id`；否则留空。
- `annotator_id`：匿名代号，不填邮箱或姓名。`notes` 简述困难判断的依据。

填写后运行 `uv run python scripts/eval/report.py`，得到 `report.json`，包含各对象已标注数量、基线与来源标记排序的 `P@5` 和返回数。少于 5 个已判候选时 `P@5` 为 N/A；该小数据集有人工挑选偏差，报告中会明确说明。反馈带来的排序改善需要另行收集用户偏好标签，不能由来源标记对比推断。完整规则见 [`../../docs/eval/protocol.md`](../../docs/eval/protocol.md)。

## 2026-10-06 Agent 补全

- `uv run python scripts/eval/agent_regression.py`：临时合成 SQLite 数据库、脚本模拟模型响应，18 个程序回归场景。报告写入 `data/eval/agent-regression.json`。不是实际模型质量或真实新闻 Eval。
- 已导出 `data/eval/20261006/annotation_queue.csv`（65 条文章链接、130 个空白判断），需人工填写。至少先核对 30 条不同文章的标签和来源；不要让模型自动填表冒充人工。
- 报告保留原始排名前五，不删除未标注候选，只有前五全标注才计算 P@5。
- 运行报告：`uv run python scripts/eval/report.py --items data/eval/20261006/items.jsonl --labels data/eval/20261006/annotation_queue.csv --output data/eval/20261006/report.json`。当前实际人工标签 0，不存在可报告的相关性分数。

## 浏览器兴趣标注

无需编辑 CSV，在项目目录运行：

```bash
uv run python scripts/eval/annotation_page.py
uv run python -m http.server 8766 --bind 127.0.0.1 --directory data/eval/20261008-labeling
```

打开 `http://127.0.0.1:8766/`，逐篇选择“想看 / 不想看 / 无法判断”，点击“下一篇”继续。浏览器自动保存进度，结束后点击“导出结果 JSON”；也可以导入同一批样本的 JSON 恢复进度。仅本机可访问，服务器只提供标注目录。

这批冻结样本包含 6 篇通鼎互联、4 篇辉煌科技、20 篇 CS2 历史文章。请判断内容兴趣，暂时忽略文章日期较早；信息不足可跳过。没有专门的 Team Spirit 新闻，不能据此声称战队新闻推荐有效。选择规则在标注之前固定，将 11 篇作为反馈组、19 篇作为留出评估组，避免把同一条标签同时用于调整排序和证明提升。

导出格式为兴趣偏好 JSON，与上面的相关性 CSV 是不同标注任务，不能直接交给 `report.py`。运行 `uv run python scripts/eval/preference_report.py`，用生产排序函数在隔离数据库中比较原始排序和反馈排序，输出 `preference-report.json`；“无法判断”不计作负例，未完成的前五不能计算完整 P@5。2026-10-08 用户已完成 30 篇标注：28 条明确判断、2 条无法判断。结果与局限见 [首轮报告](../../docs/eval/preference-results-20261008.md)。
