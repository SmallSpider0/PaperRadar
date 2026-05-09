# PaperRadar Topic Profile：Benchmark / 增量链路 / 定期修复

更新日期：2026-03-26

## 本轮完成内容

围绕 `docs/topic-profile-stage2-wrapup-and-next-plan.md` 中的后续顺序，本轮先把三件事补齐：

1. benchmark / 回归评测脚手架
2. topic profile 增量生成链路
3. topic profile 定期修复任务

并且**没有继续花时间抠“密码学”顶层 query 纯度**。

---

## 1. Benchmark / 回归评测

新增：

- `app/scripts/benchmark_topic_search.py`
- `docs/topic-search-benchmark.json`

### 当前 benchmark 设计

每个 case 定义：

- `query`
- `queries.direct`
- `queries.chat`
- `description`
- `bucket`
- `failure_mode_hint`
- `expected_topic_labels`
- `gold_papers`
- `top_k`

脚本会输出：

- direct search / chat search 两条入口各自的：
- `predicted_topic_labels`
- `matched_topic_labels`
- `gold_hit_titles`
- `missing_from_corpus_titles`
- `present_but_not_returned_titles`
- `corpus_coverage`（仅 `core/required`）
- `expanded_corpus_coverage`（`core + strong`）
- `cases_with_any_in_corpus_required_gold`
- `cases_with_full_corpus_coverage`
- `cases_with_any_in_corpus_expanded_gold`
- `cases_with_full_expanded_corpus_coverage`
- `core_recall_at_*`
- `expanded_recall_at_*`
- 各自对应的 `*_evaluable_case_count`
- `top10_topic_purity`
- `top10_canonical_purity`（当 case 提供 `canonical_gold_papers` 时）
- `tier_breakdown`
- `top_results`
- retrieval summary
- 以及 direct vs chat 的指标差值

### 当前 recall 口径

- `core_recall_at_*`：只统计 `tier in {core, required}` 的在库 gold
- `expanded_recall_at_*`：统计 `tier in {core, required, strong}` 的在库 gold

这样可以把“严格核心召回”与“扩展候选覆盖”分开看，避免数据集已经扩成多层 gold，但 summary 仍只按 `core` 解读。

### 当前错误分类字段

新增：

- `failure_mode_hint`

用于标记这个 case 当前主要想暴露哪类问题，便于 benchmark fail 后按类型选修法，而不是默认一律去调 rerank 或一律去加 topic。

当前建议的取值包括：

- `parent-swallows-child`
- `broad-topic-overexpands`
- `gold-set-risk`
- `parser-structuring`
- `filter-and-phrase`
- `alias-normalization`

这不是严格真值标签，而是**当前阶段的主要诊断入口**。

### broad aggregate topic 的 prototype 口径

对 `privacy-preserving computation` 这类 broad aggregate topic，后续不应只保留一套 `gold_papers`。

建议逐步拆成两层：

- `gold_papers`
  - 用于 coverage / recall
  - 回答“相关论文有没有被召回到”
- `canonical_gold_papers`
  - 用于 canonical purity
  - 回答“前排是不是该 topic 更有代表性的 canonical 论文”

`canonical_gold_papers` 允许只覆盖 broad topic 的若干**代表性子簇**，而不要求穷尽所有相关论文。

脚本侧当前已支持：

- `top10_canonical_purity`

它与 `top10_topic_purity` 的区别是：

- `top10_topic_purity` 更接近 in-corpus gold density
- `top10_canonical_purity` 更接近 canonical front-page density

### 当前覆盖主题

- 同态加密
- 零知识证明
- 安全多方计算
- 隐私计算
- 模糊测试
- 程序分析
- 恶意软件检测
- Web 安全
- AI 安全
- LLM 安全
- 会议+年份+术语组合 query
- 缩写 alias query（如 `MPC`）
- chat-style 自然语言问法 vs direct-style 简短 query

### 运行方式

全量：

```bash
python app/scripts/benchmark_topic_search.py
```

只测 direct：

```bash
python app/scripts/benchmark_topic_search.py --mode direct --summary-only
```

只测某些 case：

```bash
python app/scripts/benchmark_topic_search.py --mode direct --case fuzzing --case program-analysis
```

按 bucket 跑：

```bash
python app/scripts/benchmark_topic_search.py --mode direct --bucket direct-style
```

落完整结果到文件：

```bash
python app/scripts/benchmark_topic_search.py --mode direct --output /tmp/paperradar-direct.json --summary-only
```

建议：

- 每次改 `chat_parser.py` / `chat_search.py` / `search.py` 后跑一次
- 先看 summary 里的 direct/chat 分入口统计，再抽查失败 case 的 top results
- 对 `direct-style` 与 `broad-topic` 分 bucket 单独看，不要只看全量平均值

### 2026-03-30：当前 direct 聚焦结论

这轮继续按 **direct 优先** 的策略看 benchmark，结论更明确了：

- `direct-style` 这批 systems-security boundary case 整体已经相对稳定
- 当前更值得优先处理的，是 `broad-topic` 里的 **broad parent 过宽展开** 问题

按 bucket 看，当前大致表现为：

- `direct-style`
  - `avg_core_recall_at_10 = 0.75`
  - `avg_core_recall_at_20 = 0.9167`
  - `avg_expanded_recall_at_10 = 0.8056`
  - `avg_top10_topic_purity = 0.3833`
- `broad-topic`
  - `avg_core_recall_at_10 = 0.625`
  - `avg_core_recall_at_20 = 0.75`
  - `avg_expanded_recall_at_10 = 0.4167`
  - `avg_top10_topic_purity = 0.25`

当前 broad-topic 中更明显的薄弱项包括：

- `privacy-computing`
- `malware-detection`
- `homomorphic-encryption` / `zero-knowledge-proofs` 这类 broad-topic purity 仍偏低的 case

### 2026-03-30：为 FHE / ZKP 补 canonical gold

这一轮先不急着给 `homomorphic-encryption` / `zero-knowledge-proofs` 做 heuristic 微调，而是先把 benchmark 观察面补齐。

已补内容：

- `homomorphic-encryption`
  - `fhe-security`
  - `tfhe-systems`
  - `threshold-fhe`
  - `tfhe-evaluation`
- `zero-knowledge-proofs`
  - `zk-snark-overview`
  - `distributed-proof-delegation`
  - `zk-for-he`
  - `zk-for-llm-inference`

这样后面再看这两个 broad-topic case 时，就不会只看到 coverage / topic purity，而能同时看：

- `top10_topic_purity`
- `top10_canonical_purity`

也就是把“召回到了很多相关论文”与“前排是否像一个 canonical front page”分开判断。

补完后跑了一次 direct benchmark，当前可先这样看：

- `homomorphic-encryption`
  - `core@10 = 0.5`
  - `expanded@10 = 0.6667`
  - `top10_topic_purity = 0.4`
  - `top10_canonical_purity = 0.2`
- `zero-knowledge-proofs`
  - `core@10 = 1.0`
  - `expanded@10 = 0.5`
  - `top10_topic_purity = 0.3`
  - `top10_canonical_purity = 0.3`

这说明：

- `homomorphic-encryption` 当前更像 canonical front-page 还没立稳
- `zero-knowledge-proofs` 的 canonical/front-page 表现略健康一些，但仍不是特别高 purity 的 broad-topic case

因此在 broad-topic 队列里，现阶段优先级仍然可以维持为：

1. 继续推进 `malware-detection`
2. 观察 `homomorphic-encryption`
3. 再看 `zero-knowledge-proofs`
4. `privacy-computing` 暂不继续做轻量 heuristic 硬修

### 2026-03-30：当前执行策略（按 direct search 稳定性）

如果当前目标是先把 **direct search 做稳**，则可以把 broad-topic 的执行策略进一步写死为：

- `malware-detection`
  - 继续做前排相关性精修
  - 接受“结构改善 > 指标立刻上涨”
- `homomorphic-encryption`
  - 只做 parser / taxonomy 小步收敛
  - 目标是保持 direct top10 稳定聚焦 FHE 主体
- `zero-knowledge-proofs`
  - 暂缓，不主动投入新的 heuristic 微调
  - 等 malware / FHE 稳住后再回头看
- `privacy-computing`
  - 暂停轻量 heuristic 微调
  - 如后续重启，直接走 prototype-aware candidate shaping / seed retrieval

### 2026-03-30：第二轮 broad-topic 推进后的停止条件

第二轮又分别对 `malware-detection` 与 `homomorphic-encryption` 做了一次小步推进后，可以进一步明确：

#### `malware-detection`
- 虽然 `top10_canonical_purity` 仍停在 `0.3`
- 但前 10 里的 `binary naming / stripped binary` 漂移项已继续减少
- 说明这条线仍然可以做，只是收益开始变成**结构改善先于指标改善**

因此后续继续推进时，要接受一个现实：

- 单轮小修不一定立刻涨 purity 指标
- 但只要前排结构持续更接近 canonical front page，这条线仍然值得做

#### `homomorphic-encryption`
- 当前 `top10_canonical_purity` 仍是 `0.2`
- 加轻量 canonical bias 后，前排顺序有变得更像 FHE canonical front page
- 但还不足以证明单靠轻量 rerank bias 就能把它拉起来

所以这条线的停止条件应明确为：

- 如果后续 1~2 轮仍然只出现轻微排序变化，而 `top10_canonical_purity` 不动
- 就不要继续在 rerank 小权重上细拧
- 应转向：
  - taxonomy / parser shaping
  - 或更明确的 prototype-aware candidate shaping

### 2026-03-30：broad-topic 第一轮修复观察

这一轮先挑了两个 broad-topic case 下手：

- `privacy-computing`
- `malware-detection`

结论不是同一种：

#### `malware-detection`
通过收缩 taxonomy expansion，并给 generic rerank 增加 anti-drift 邻域约束后，结果有明确改善：

- topic labels 不再扩到 `malicious traffic detection` / `phishing detection`
- 前排显著更偏向：
  - `packed executables detection`
  - `android malware detection`
  - `malware classification`
- 说明这类 broad-topic 仍然可以先用：
  - taxonomy 收缩
  - 邻域负样本抑制
  来获得可见收益

#### `privacy-computing`
这类 topic 则暴露出另一种问题：

- 原来 top10 被 `differential privacy / local DP` 单一簇占满
- 收缩后，又转而被 `private set intersection / secure computation` 单一簇占满

这说明它不是简单的“多加/少加几个 term”就能修好的 case，而是：

- `privacy-preserving computation` 本身就是一个**聚合性过强的 broad aggregate topic**
- 其 canonical 前排需要在多个子簇之间做更明确的 prototype / coverage / canonical 区分

所以对这类 topic，不建议继续只靠 heuristic 小修，而应进入下一层方案：

1. 为 broad aggregate topic 建 `prototype` / canonical seed
2. benchmark 上把 `coverage gold` 与 `canonical gold` 分开
3. 必要时对前排做轻量 diversification，而不是只让单一子簇霸榜

#### `privacy-preserving computation` 的 prototype 草案

当前更适合把它看作一个 **broad aggregate topic**，而不是单一 canonical cluster。

第一版 prototype 可先按代表性子簇组织：

- `encrypted-search`
- `private-inference`
- `ppml`
- `privacy-learning`
- （后续可扩）`secure-aggregation` / `private-set-intersection`

其中：

- `gold_papers` 继续承担 coverage 目标
- `canonical_gold_papers` 只挑每个代表性子簇里更像“用户搜隐私计算时希望前排看到”的论文

这样后面如果 top10 被：

- 纯 `local differential privacy` 单簇占满
- 或纯 `private set intersection` 单簇占满

就可以明确判成：

- recall 未必错
- 但 canonical front-page 失衡

这比继续把问题归到“词没配好 / rerank 不够狠”更准确。

#### 2026-03-30：prototype diversification 第一轮实验结论

这轮还试了一版**最小 rerank 后处理 diversification**，希望在 `privacy-preserving computation` 上抑制单簇霸榜。

结论：**当前不值得继续沿这条实现细拧。**

原因是：

- 仅在 rerank 末端做“子簇均衡”太晚
- 候选池与前置 topic/profile 定义仍然偏向某些强簇
- 结果容易把当前 coverage gold 进一步打坏，而不是真正提升 canonical front-page

因此下一步更合理的顺序应是：

1. 先定义更清楚的 topic prototype / canonical seed
2. 必要时让 candidate generation 或 query profile 就感知 prototype
3. 最后才考虑 rerank 末端的轻量 diversification

也就是说，`privacy-preserving computation` 当前**不适合先从 rerank tail-end diversification 开刀**。

#### 2026-03-30：prototype-aware query/profile shaping 观察

在放弃 tail-end diversification 之后，又试了一版**前移到 parser / query profile 的 shaping**：

- 对 `隐私计算` / `privacy-preserving computation` 显式提升：
  - `privacy-preserving machine learning`
  - `private inference`
  - `encrypted search`
  - `secure aggregation`
- 同时对以下簇增加负向约束：
  - `local differential privacy`
  - `frequency estimation`
  - `shuffle protocol`
  - `randomized response`

结论：

- 这条路线比 tail-end diversification 更合理
- 但仍然没有把 benchmark 拉到“可接受的 canonical front-page”
- 前排从 `local DP` 漂移，转成了 `private set intersection / private inference / private computation` 混合簇主导

这进一步说明：

- 仅靠轻量 shaping，仍不足以定义好 `privacy-preserving computation` 的 canonical front-page
- 后续若继续做实现，应该优先往：
  - candidate generation / route shaping
  - prototype-aware seed retrieval
  - canonical gold 对齐
 这些更前置的层面推进

因此下一步建议是：

1. 继续把 broad-topic parent canonical 化
2. 优先从 `topic_taxonomy.py` / parser 侧收缩 broad parent 的 expansion
3. 在 benchmark 上把 recall gold 与更严格的 canonical purity gold 逐步拆开

另外，这轮还暴露出一个 benchmark 解读上的提醒：

- `fuzzing` 当前 `core@10` 偏低，但 top10 已基本被 fuzzing 论文占满
- 这类 case 不一定是 retrieval fail，也可能是 **当前 core gold 太窄 / 太旧**

所以看 direct benchmark 时，要把两类问题分开：

- 真正的 retrieval / topic boundary 问题
- benchmark gold 本身需要重构的问题

### 当前定位

这版 benchmark 已经从单入口 topic regression net 扩成**双入口 + 本地语料校验**回归网，但仍不是最终评测体系。

现在解读结果时，建议先看两层：

- 第一层：`corpus_coverage` / `missing_from_corpus_titles`
- 第二层：在 gold 已在库的前提下，再看 `recall_at_k`

另外要结合 `*_evaluable_case_count` 一起看平均值。
如果只有极少数 case 有在库 gold，那么 `avg_recall_at_50 = 1.0` 也不代表系统整体很好，只代表“那几个可评 case”命中了。

也就是说，低 recall 不再默认等于“检索差”，可能只是 gold 论文本身不在当前语料。

后续可继续补：

- 更多 query 变体（中英混输、口语化问法、作者名、方法名）
- `paper_id` 级 gold set，减少 title exact match 误差
- “明显跑偏样本数” 自动统计
- 失败 case 快照落盘

---

## 2. Topic Profile 增量生成链路

新增：

- `app/scripts/topic_profile_lib.py`
- `app/scripts/build_topic_profiles_incremental.py`

并把：

- `app/scripts/build_topic_profiles.py`

重构为复用共享库，不再把所有 topic profile 逻辑都堆在单文件里。

### 当前实现

`ingest_papers_to_postgres.py` 在 metadata 入库完成后，会收集本次 ingest 的 `paper_id`，然后调用：

```bash
python app/scripts/build_topic_profiles_incremental.py <paper_id...>
```

默认行为：

- 开启增量 topic profile（`PAPERRADAR_TOPIC_INCREMENTAL=1`）
- ingest 成功后立即为本批 paper 生成 topic profile
- 仍复用已有模型调用 / fallback / run logging 逻辑

### 设计取舍

当前先做成**脚本级串联**，而不是直接塞进更复杂的后台任务系统，原因：

- 现有 ingest 流程本来就是脚本驱动
- 这样改动面最小
- 更容易观察失败点
- 后续真要做异步队列，再把这层抽出去即可

### 可控开关

如需临时关闭 ingest 后自动 topic profile：

```bash
PAPERRADAR_TOPIC_INCREMENTAL=0 python app/scripts/ingest_papers_to_postgres.py
```

---

## 3. Topic Profile 定期修复任务

新增：

- `app/scripts/topic_profile_maintenance.py`

### 当前支持的修复模式

#### `empty_tags`

修复：

- `paper_topic_profiles.topic_tags = []`

运行：

```bash
python app/scripts/topic_profile_maintenance.py empty_tags 50
```

#### `max_tokens`

修复：

- `paper_topic_profile_runs.finish_reason = 'MAX_TOKENS'`
- 会取这些 run 对应的 `paper_id` 做定向重刷

运行：

```bash
python app/scripts/topic_profile_maintenance.py max_tokens 50
```

#### `missing`

修复：

- 还没有 topic profile 的 paper

运行：

```bash
python app/scripts/topic_profile_maintenance.py missing 50
```

### 当前定位

这一步先做成**低频手动 / cron 可调用脚本**。

后续如果要真正接系统定时任务，建议直接用这层脚本，不要再重写一套逻辑。

例如：

```bash
# 每天凌晨修空 tag
python app/scripts/topic_profile_maintenance.py empty_tags 30

# 每周低频修一批 MAX_TOKENS
python app/scripts/topic_profile_maintenance.py max_tokens 30
```

---

## 推荐运行顺序

### 开发回归时

```bash
python app/scripts/benchmark_topic_search.py
```

### 新论文 ingest 后

```bash
python app/scripts/ingest_papers_to_postgres.py
```

它会默认触发增量 topic profile。

### 日常低频修复

```bash
python app/scripts/topic_profile_maintenance.py empty_tags 30
python app/scripts/topic_profile_maintenance.py max_tokens 30
```

---

## 当前状态判断

这轮之后，topic profile 这条线已经从“验证可行”推进到“可持续维护”：

- 有 benchmark
- 有增量生成
- 有修复入口

下一步如果继续推进，优先级应该是：

1. 跑 benchmark，看当前基线
2. 根据 benchmark 失败 case 做 retrieval 微调
3. 再考虑是否把 maintenance 挂进系统级 cron / deploy 流程

而不是回去继续死抠 `密码学` 顶层泛词。
