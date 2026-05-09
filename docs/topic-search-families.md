# Topic search families（query family 诊断）

## 目的

把 benchmark 从「单条 query 调参」升级为 **family 级回归**：同一 `family_id` 下聚合主 case 的 `direct`/`chat` 结果与可选 `paraphrase_queries`，观察跨措辞的 recall / canonical purity / prototype 覆盖是否稳定。

运行时检索策略仍以 [`app/backend/config/topic_profiles.json`](../app/backend/config/topic_profiles.json) 为准；本文件与 [`docs/topic-search-benchmark.json`](topic-search-benchmark.json) 只做**诊断与回归**，不驱动业务配置。

## JSON 字段

- **`family_id`**：族标识；未写时脚本回退为 case 的 `id`。
- **`paraphrase_queries`**（可选）：列表项形如  
  `{ "label": "en-broad", "modes": ["direct"], "query": "malware detection" }`  
  - `modes` 省略时默认 `direct` + `chat`；与 CLI `--mode` 过滤一致。

## 指标（脚本输出）

- **`prototype_role_coverage_at_10`**：若存在带 `role` 的 `canonical_gold_papers`，top10 中命中了多少**不同 role**（相对在库 canonical 角色总数）。用于 broad aggregate / 多 prototype 前排覆盖。
- **`summary.families.<mode>.<family_id>`**：
  - `row_count`：主 modes + paraphrase 行数
  - `avg_core_recall_at_10` / `min` / `max` / `stdev_core_recall_at_10`
  - `avg_top10_canonical_purity`
  - `avg_prototype_role_coverage_at_10`
  - `topic_label_hit_rate`

## 运行

```bash
cd app && python scripts/benchmark_topic_search.py --mode direct --summary-only
```

查看 `summary.families.direct` 即可做 family 级对比。
