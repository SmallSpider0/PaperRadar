# PaperRadar Topic Profile 阶段收尾与后续实施清单

更新日期：2026-03-26

## 本阶段目标

解决泛词搜索（尤其是“密码学 / 同态加密 / 零知识证明 / 安全多方计算 / 隐私计算”等）只靠标题/摘要字面命中、导致部分主题词搜不到或召回不稳的问题。

核心思路：

- query 侧：broad-topic 识别 + topic taxonomy 扩展
- paper 侧：topic profile（`topic_tags` + `topic_summary`）
- ranking 侧：topic-aware lexical + semantic + rerank 融合

---

## 本阶段已完成内容

### 1. broad-topic 检索增强

已完成：

- 新增 `topic_taxonomy.py`
- 对以下主题做 canonical taxonomy / alias / zh_aliases 扩展：
  - cryptography
  - homomorphic encryption
  - zero-knowledge proofs
  - secure multiparty computation
  - privacy-preserving computation
  - privacy-preserving machine learning
  - anonymous credentials
  - digital signatures
  - program analysis
  - fuzzing
  - malware detection
  - web security
  - adversarial machine learning
  - hardware security
  - ai security
  - llm safety
  - security governance
  - vulnerability management
  - usable security
  - security training

### 2. parser / search / rerank 改造

已完成：

- `chat_parser.py`
  - broad-topic generic query 识别
  - `topic_labels` 产出
  - query variants 扩展
- `chat_models.py`
  - `StructuredQuery` 新增 `topic_labels`
- `chat_search.py`
  - 把 `topic_labels` 纳入 query variants 与 match reasons
- `search.py`
  - 读取并使用 paper-side `topic_tags` / `topic_summary`
  - keyword score 支持 topic hits
  - rerank 支持 topic bonus
  - broad-topic 下 generic query 提升 recall 与 semantic-first 融合

### 3. paper-side topic profile 存储与生成

已完成：

- `schema.sql`
  - 新增 `paper_topic_profiles`
  - 新增 `paper_topic_profile_runs`
- `scripts/build_topic_profiles.py`
  - 生成 `topic_tags` + `topic_summary`
  - 支持 retry
  - 支持解析失败容错
  - 支持 `MAX_TOKENS` 诊断
  - 支持低并发限速批处理
  - 支持空 tag 重刷
  - 支持 fallback 规则补标签
- 默认批处理参数已调为：
  - `workers = 16`
  - `RPS = 8`

### 4. topic profile 诊断与稳定性收尾

已完成：

- 新增运行诊断表 `paper_topic_profile_runs`
- 记录：
  - success / failed
  - finish_reason
  - token usage
  - raw_response_text
- 确认并修复了一轮关键问题：
  - 坏 JSON 主要由 `MAX_TOKENS` 截断导致
  - 通过缩短 prompt + 缩小候选 taxonomy + 提高 output tokens + retry，有效降低了截断比例

---

## 当前结果（截至本轮结束）

### topic profile 覆盖情况

- `paper_topic_profiles = 119`
- `non_empty_tags = 117`
- `empty_tags = 2`

### 运行统计

- `success + STOP = 244`
- `failed + MAX_TOKENS = 9`
- `success + MAX_TOKENS = 1`

### 效果结论

当前已经明确改善的 broad-topic 检索方向包括：

- 隐私计算
- 同态加密
- 零知识证明
- 安全多方计算
- 匿名认证
- 数字签名
- 模糊测试
- 程序分析
- 恶意软件检测
- Web 安全

结论：

- 中等粒度主题检索已经达到明显可用
- topic profile 路线已验证成功
- 当前不再需要继续反复补 topic profile 主链路

---

## 当前未完全收口的点

### 1. 剩余空 tag 仅 2 条

当前剩余：

1. `ImportSnare: Directed ”Code Manual” Hijacking in Retrieval-Augmented Code Generation`
2. `WhisperTest: A Cross-Platform Library for iOS UI Automation`

判断：

- `ImportSnare` 可继续吃到 `ai security / code generation security / rag security` 方向
- `WhisperTest` 更像一般工具类 paper，不一定值得强打安全主题标签

因此这 2 条不再是当前主要矛盾。

### 2. `密码学` 顶层泛词排序仍不够理想

已尝试的优化包括：

- broad-topic must_terms 收紧
- crypto 子方向 bonus
- 非技术 meta 论文轻度 penalty
- query expansion 收紧

当前判断：

- 已有改善
- 但 `cryptography` 顶层 query 仍偏向标题里显式含 `cryptography / cryptographic` 的论文
- 如果后续继续做，应视作一个新的独立小目标，而不是继续归在 topic profile 主链路中

---

## 推荐的后续实施顺序

### P1. 建 benchmark / 回归评测集（强烈推荐优先）

目标：

避免后续改搜索时把当前已验证的效果做坏。

建议覆盖：

- 密码学
- 隐私计算
- 同态加密
- 零知识证明
- 安全多方计算
- 匿名认证
- 数字签名
- 模糊测试
- 程序分析
- 恶意软件检测
- Web 安全
- AI 安全 / LLM 安全

建议指标：

- Top-10 主题纯度
- Recall@20
- 是否命中代表论文
- 明显跑偏样本数

### P2. 把 topic profile 接入增量更新链路

目标：

新论文入库后自动生成 topic profile，而不是依赖人工手动跑脚本。

建议：

- 在 ingest / metadata / embedding 后接 topic profile 生成
- 写入 `paper_topic_profiles`
- 失败写入 `paper_topic_profile_runs`
- 定期 retry 失败样本

### P3. 做定期修复任务（低频增量）

目标：

持续维护 topic profile 质量。

建议修复目标：

- `topic_tags = []`
- `finish_reason = MAX_TOKENS`
- taxonomy 升级后需重刷的 profile

建议运行参数：

- `workers = 16`
- `RPS = 8`
- 仅小批量定期运行，不全量暴刷

### P4. 若后续需要，再单开“密码学顶层 query 纯度优化”小目标

建议作为独立后续项，而不是继续混在当前阶段里。

---

## 涉及文件（本阶段关键）

### 后端

- `app/backend/topic_taxonomy.py`
- `app/backend/chat_models.py`
- `app/backend/chat_parser.py`
- `app/backend/chat_search.py`
- `app/backend/search.py`
- `app/backend/schema.sql`

### 脚本

- `app/scripts/build_topic_profiles.py`

### 文档

- `docs/topic-profile-stage2-wrapup-and-next-plan.md`（本文）

---

## 下次继续时建议优先做什么

优先做：

1. benchmark / 回归评测
2. topic profile 接入增量生成链路
3. 定期修复任务

不建议优先做：

- 再继续盯着那 2 条空 tag 反复刷
- 继续在当前阶段死抠 `密码学` 顶层词

因为这两者都不是当前最有收益的工作。
