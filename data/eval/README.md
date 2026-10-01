# Eval 数据目录

`annotation_template.csv` 是空白模板。运行 `uv run python scripts/eval/prepare.py` 会从本地数据库导出 `items.jsonl` 与 `annotation_queue.csv`：目前 35 条真实原文链接，每条分别对所属关注对象和一个容易混淆的其他对象标注，共 70 个待判断位置。脚本在清单已存在时拒绝覆盖，以免丢失人工标注。生成文件和个人阅读/反馈记录均不提交到 Git。

打开 `annotation_queue.csv`，逐行核对 `canonical_url`，填写：

- `relevance`：有实质新信息填 `1`；无关、纯重复、明显过时或标题党填 `0`。
- `entity_match`：确实属于 `watch_id` 对象填 `1`，否则填 `0`。
- `duplicate_of`：如同事件重复，填主样本 `sample_id`；否则留空。
- `annotator_id`：匿名代号，不填邮箱或姓名。`notes` 简述困难判断的依据。

填写后运行 `uv run python scripts/eval/report.py`，得到 `report.json`，包含各对象已标注数量、基线与来源标记排序的 `P@5` 和返回数。少于 5 个已判候选时 `P@5` 为 N/A；该小数据集有人工挑选偏差，报告中会明确说明。反馈带来的排序改善需要另行收集用户偏好标签，不能由来源标记对比推断。完整规则见 [`../../docs/eval/protocol.md`](../../docs/eval/protocol.md)。
