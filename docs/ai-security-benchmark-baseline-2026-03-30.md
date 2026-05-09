# AI Security Benchmark Baseline — 2026-03-30

## Scope

冻结本轮 `docs/topic-search-benchmark.json` 基线口径后，先记录 `ai-security` 相关 case 的 direct baseline，作为后续 candidate shaping / rerank / expansion 清理的对照面。

基线文件版本：`docs/topic-search-benchmark.json`（当前 config.version = 6）

数据来源：
- 子集 direct benchmark 输出：`/tmp/paperradar-ai-security-baseline.json`
- 后续全量 direct summary 仍建议补跑并追加到本文档

## 当前 direct baseline 摘要（ai-security 子集）

| case | core_recall@10 | expanded_recall@10 | top10_topic_purity |
|---|---:|---:|---:|
| rag-codegen-security | 0.0 | 0.0 | 0.0 |
| prompt-injection-rag-security | 1.0 | 1.0 | 0.3 |
| training-data-poisoning-security | 0.0 | 0.0 | 0.0 |
| model-backdoor-security | N/A* | 0.0 | 0.0 |
| llm-backdoor-security | 1.0 | 0.6667 | 0.2 |
| training-data-extraction-security | 1.0 | 1.0 | 0.3 |
| prompt-ip-leakage-security | 0.0 | 0.0 | 0.0 |

> `model-backdoor-security` 的 core gold 当前存在 paper_id 对齐问题，因此 `core_recall@10` 为 N/A；但 expanded baseline 仍可用于观察排序偏差。

---

## Case snapshots

### 1) rag-codegen-security
- `core_recall@10 = 0.0`
- `expanded_recall@10 = 0.0`
- `top10_topic_purity = 0.0`
- 当前 top5：
  1. TwinBreak: Jailbreaking LLM Security Alignments based on Twin Prompts
  2. Topic-FlipRAG: Topic-Orientated Adversarial Opinion Manipulation Attacks to Retrieval-Augmented Generation Models
  3. StruQ: Defending Against Prompt Injection with Structured Queries
  4. Fun-tuning: Characterizing the Vulnerability of Proprietary LLMs to Optimization-based Prompt Injection Attacks via the Fine-Tuning Interface
  5. DataSentinel: A Game-Theoretic Detection of Prompt Injection Attacks
- 诊断：`ImportSnare` 完全没进 top10；query 仍被 umbrella 下 `jailbreak/prompt-injection` 强簇吞没。

### 2) prompt-injection-rag-security
- `core_recall@10 = 1.0`
- `expanded_recall@10 = 1.0`
- `top10_topic_purity = 0.3`
- 当前 top5：
  1. TwinBreak: Jailbreaking LLM Security Alignments based on Twin Prompts
  2. Topic-FlipRAG: Topic-Orientated Adversarial Opinion Manipulation Attacks to Retrieval-Augmented Generation Models
  3. StruQ: Defending Against Prompt Injection with Structured Queries
  4. Fun-tuning: Characterizing the Vulnerability of Proprietary LLMs to Optimization-based Prompt Injection Attacks via the Fine-Tuning Interface
  5. DataSentinel: A Game-Theoretic Detection of Prompt Injection Attacks
- 诊断：召回已通，但 top1 仍被 jailbreak 论文占住，说明仍有 umbrella 杂糅。

### 3) training-data-poisoning-security
- `core_recall@10 = 0.0`
- `expanded_recall@10 = 0.0`
- `top10_topic_purity = 0.0`
- 当前 top5：
  1. Mitigating Data Poisoning Attacks to Local Differential Privacy
  2. On the Robustness of LDP Protocols for Numerical Attributes under Data Poisoning Attacks
  3. Cascading Adversarial Bias from Injection to Distillation in Language Models
  4. A Practical and Secure Byzantine Robust Aggregator
  5. AlphaDog: No-Box Camouflage Attacks via Alpha Channel Oversight
- 诊断：出现了“poisoning”词面命中，但主要落在 DP / aggregation 邻域，而非目标训练期 poisoning / clean-label backdoor 子簇。

### 4) model-backdoor-security
- `core_recall@10 = N/A`
- `expanded_recall@10 = 0.0`
- `top10_topic_purity = 0.0`
- 当前 top5：
  1. SelfDefend: LLMs Can Defend Themselves against Jailbreaking in a Practical Manner
  2. Mitigating Data Poisoning Attacks to Local Differential Privacy
  3. Data-Free Model-Related Attacks: Unleashing the Potential of Generative AI
  4. Membership Inference Attacks Against Vision-Language Models
  5. Black-box Membership Inference Attacks against Fine-tuned Diffusion Models
- 诊断：当前仍被 generic AI-security / privacy / poisoning 邻域污染，top5 还不像“模型后门论文前页”。

### 5) llm-backdoor-security
- `core_recall@10 = 1.0`
- `expanded_recall@10 = 0.6667`
- `top10_topic_purity = 0.2`
- 当前 top5：
  1. SelfDefend: LLMs Can Defend Themselves against Jailbreaking in a Practical Manner
  2. PEFTGuard: Detecting Backdoor Attacks Against Parameter-Efficient Fine-Tuning
  3. Mitigating Data Poisoning Attacks to Local Differential Privacy
  4. Membership Inference Attacks Against Vision-Language Models
  5. On the Robustness of LDP Protocols for Numerical Attributes under Data Poisoning Attacks
- 诊断：核心论文已进 top10，但头部仍有明显杂质。

### 6) training-data-extraction-security
- `core_recall@10 = 1.0`
- `expanded_recall@10 = 1.0`
- `top10_topic_purity = 0.3`
- 当前 top5：
  1. GPU Travelling: Efficient Confidential Collaborative Training with TEE-Enabled GPUs
  2. Effective PII Extraction from LLMs through Augmented Few-Shot Learning
  3. Private Investigator: Extracting Personally Identifiable Information from Large Language Models Using Optimized Prompts
  4. PrivacyXray: Detecting Privacy Breaches in LLMs through Semantic Consistency and Probability Certainty
  5. Generated Data with Fake Privacy: Hidden Dangers of Fine-tuning Large Language Models on Generated Data
- 诊断：主线已可用，但 top1 仍混入 confidentiality / TEE 邻域论文。

### 7) prompt-ip-leakage-security
- `core_recall@10 = 0.0`
- `expanded_recall@10 = 0.0`
- `top10_topic_purity = 0.0`
- 当前 top5：
  1. TwinBreak: Jailbreaking LLM Security Alignments based on Twin Prompts
  2. Topic-FlipRAG: Topic-Orientated Adversarial Opinion Manipulation Attacks to Retrieval-Augmented Generation Models
  3. StruQ: Defending Against Prompt Injection with Structured Queries
  4. SelfDefend: LLMs Can Defend Themselves against Jailbreaking in a Practical Manner
  5. Great, Now Write an Article About That: The Crescendo Multi-Turn LLM Jailbreak Attack
- 诊断：query 明明命中了 `prompt stealing / system prompt`，但当前 top10 prototype bucket 仍是 `llm-jailbreaks:5 + prompt-injection-rag:5`，说明 prompt-IP 子簇在 candidate / rerank 两层都不够强。

---

## 基线结论

本轮 baseline 最重要的结论不是“ai-security 搜不到”，而是：

1. `prompt-injection-rag` / `llm-jailbreak` 这两个高频强簇仍然占据 umbrella 头部。
2. `training-data-poisoning` / `prompt-ip` / `rag-codegen` 三条垂直 case 的主要问题是：
   - query 已经有方向词
   - 目标论文也在库里
   - 但 candidate 与 rerank 都还不够 prototype-aware
3. 当前后续优化应继续遵循：
   - 先做 query→prototype candidate shaping
   - 再做小白名单 prototype-aware rerank
   - 最后清 generic expansions
   - 避免继续无界扩 umbrella 结构
