# AI Security 子族拆分底稿（2026-03-30）

更新日期：2026-03-30

## 背景

当前 `ai-security` 已能作为 broad aggregate runtime profile 工作，但它覆盖的论文簇过宽：

- jailbreak / alignment break
- prompt injection / RAG manipulation
- RAG code generation / dependency hijacking
- agentic LLM / tool-use security
- LLM app ecosystem / app store security
- model-as-malware / model misuse
- model poisoning / backdoor / extraction / privacy leakage / watermarking

因此当 query 仍停留在顶层 `ai security` 时，排序会自然坍缩到最密集、语义最稳定的几个子簇（当前主要是 jailbreak 与 prompt injection），不适合再把所有问题都视作单一 family 的排序问题。

结论：后续应优先把 `ai-security` 视作 umbrella family，把 benchmark / family / prototype 观察面拆细，而不是继续只在顶层 broad query 上拧 heuristic。

---

## 建议的一级子族（更细拆版）

### A. `llm-interaction-security`

这是 **LLM 在交互/推理期被操纵** 的总类，下面建议再拆四个二级子族：

#### A1. `llm-jailbreak-security`

**范围**

- jailbreak attacks
- jailbreak defense
- safety alignment breaking
- refusal bypass / alignment manipulation

**代表论文**

- `JBShield`
- `SelfDefend`
- `TwinBreak`

#### A2. `prompt-injection-rag-security`

**范围**

- prompt injection
- retrieval-augmented generation manipulation
- structured query / context boundary breaking
- retrieval-driven opinion manipulation

**代表论文**

- `StruQ`
- `Topic-FlipRAG`
- `DataSentinel`

#### A3. `rag-codegen-security`

**范围**

- retrieval-augmented code generation
- code manual hijacking
- dependency hijacking via retrieved docs
- poisoned documentation / malicious package suggestion

**代表论文**

- `ImportSnare`

#### A4. `agentic-llm-security`

**范围**

- LLM agents
- tool-use security
- taint-style vulnerabilities in agents
- proactive defenses against agents

**代表论文**

- `Cloak, Honey, Trap`
- `Make Agent Defeat Agent`

---

### B. `llm-ecosystem-security`

这是 **LLM 应用分发、适配器、提示词、应用商店、第三方组件** 相关问题的总类。

#### B1. `llm-app-ecosystem-security`

**范围**

- LLM app stores
- plugin / app ecosystem security
- abusive-potential applications
- distribution ecosystem risk

**代表论文**

- `On the (In)Security of LLM App Stores`

#### B2. `prompt-ip-leakage-security`

**范围**

- prompt stealing
- system prompt extraction
- prompt obfuscation / prompt IP protection
- prompt marketplaces security

**代表论文线索**

- `PRSA`
- system prompt extraction / obfuscation 相关工作

#### B3. `adapter-supply-chain-security`

**范围**

- PEFT / LoRA adapter backdoors
- infected adapters
- adapter detection / purification
- open adapter marketplace security

**代表论文线索**

- `PEFTGuard`
- `POLISHED / FUSION` 感染 adapter
- `BAIT` / LLM backdoor scanning 可视作相邻工作

---

### C. `model-poisoning-and-backdoor-security`

这是你提到的重点：**模型中毒攻击与防御**。建议单独立成一级大类，而不是继续混在 `model-malware-abuse` 里。

#### C1. `training-data-poisoning-security`

**范围**

- training-time data poisoning
- clean-label / dirty-label poisoning
- poisoned sample detection / sanitization
- DaaS / dataset curation poisoning

**代表论文线索**

- `TellTale`
- 各类 poisoned sample detection / sanitization 工作

#### C2. `model-backdoor-security`

**范围**

- backdoor attacks on models
- trigger-based backdoors
- clean-label / dirty-label backdoors
- backdoor detection / reverse engineering / purification

**代表论文线索**

- `ONEFLIP`
- persistent / continual-learning backdoor
- realistic backdoor detection frameworks

#### C3. `llm-backdoor-security`

**范围**

- LLM backdoor attacks
- black-box/backbox scanning for LLM backdoors
- trigger inversion / target inversion
- fine-tuning induced LLM backdoors

**代表论文线索**

- `BAIT`
- `EmbedX`
- 各类 LLM Trojan / jailbreak-like backdoor work

#### C4. `model-supply-chain-poisoning`

**范围**

- poisoned pretrained models
- encoder poisoning
- transfer learning backdoors
- model merging induced backdoors
- architecture backdoors

**代表论文线索**

- `Trusted Core (T-Core)`
- `MergeBackdoor`
- architectural backdoor 相关工作

#### C5. `federated-poisoning-security`

**范围**

- federated learning poisoning
- Byzantine / aggregation poisoning
- clustered / semi-asynchronous FL poisoning
- robust aggregation / poisoning defense

**代表论文线索**

- `FoundationFL`
- `PoiSAFL`
- CFL / FRL / SAFL poisoning 与防御

**说明**

- 这条和一般 AI security 相关，但更贴近分布式训练安全
- 如果后续 corpus 量够大，甚至可以从 `ai-security` umbrella 中独立出去

---

### D. `model-privacy-and-extraction-security`

这是 **模型泄露、训练数据泄露、成员推断、模型窃取** 相关方向。

#### D1. `membership-inference-and-privacy-leakage`

**范围**

- membership inference attacks (MIA)
- privacy leakage after fine-tuning / transfer learning
- label-only / black-box MIAs
- MIA defenses / privacy-preserving inference defenses

#### D2. `training-data-extraction-security`

**范围**

- PII extraction from LLMs
- code/data memorization extraction
- private fine-tuning data extraction
- privacy breach detection during inference

**代表论文线索**

- `Codebreaker`
- `Private Investigator`
- `PrivacyXray`

#### D3. `model-stealing-and-functionality-theft`

**范围**

- model extraction
- prompt/service cloning
- stealing via black-box querying
- functionality theft / surrogate training

**备注**

- 对 LLM 来说，prompt stealing 与 model extraction 有重叠，但在检索意图上最好仍拆开

#### D4. `machine-unlearning-security`

**范围**

- unlearning attacks
- unlearning evaluation / inference
- exact vs approximate unlearning risks
- adversarial unlearning

**代表论文线索**

- adversarial unlearning break safety alignment
- `RULI`
- `IAM`

---

### E. `model-integrity-watermark-and-ownership`

这是 **模型完整性、归属验证、数据集版权审计、水印** 相关方向。

#### E1. `model-watermarking-and-ownership`

**范围**

- model ownership verification
- harmless watermarking
- post-hoc ownership proofs
- watermark robustness / removal attacks

#### E2. `dataset-traceability-and-copyright`

**范围**

- training data tracing
- dataset copyright auditing
- proactive coatings / data usage evidence
- personalized model misuse auditing

**代表论文线索**

- `SIREN`
- dataset copyright auditing survey

#### E3. `genai-watermark-security`

**范围**

- watermarking for LLM / diffusion / audio generation
- source tracing
- robustness against watermark removal
- attacks on defensive watermarking

**代表论文线索**

- multi-user watermarking for LLM text
- `UnMarker`
- Tree-Ring removal attack

---

### F. `model-misuse-and-weaponization`

这个类保留，但缩窄，不再一股脑接所有“坏事”。

#### F1. `model-malware-abuse`

**范围**

- model-as-malware
- abusing model artifacts / APIs for malicious behavior
- AI model transformed into attack carrier

**代表论文**

- `My Model is Malware to You`

#### F2. `generative-model-misuse-defense`

**范围**

- misuse of personalization / diffusion / T2I / TTS
- concept censorship
- proactive protections against abusive generation
- deepfake / unsafe content prevention tied to model security

**代表论文线索**

- `THEMIS`（concept censorship / TI embedding）
- Audio / image / video misuse protection 工作

---

## 推荐的结构关系

如果从更高层看，`ai-security` 更适合拆成 6 个一级总类：

1. `llm-interaction-security`
2. `llm-ecosystem-security`
3. `model-poisoning-and-backdoor-security`
4. `model-privacy-and-extraction-security`
5. `model-integrity-watermark-and-ownership`
6. `model-misuse-and-weaponization`

其中每个一级类再挂若干二级 family。

这会比之前直接把 `ImportSnare / jailbreak / app store / malware` 并列为一级 family 更稳，因为：

- 现在顶层粒度统一了
- “模型中毒攻击防御”有了正式位置
- 后续 benchmark 可以先按二级 family 加 case，不需要频繁改顶层结构

---

## 关于“模型中毒攻击防御”应如何放置

建议不要只写成一个泛泛的 `model poisoning` family，而是至少分成下面三块：

1. **训练数据中毒** `training-data-poisoning-security`
2. **模型后门** `model-backdoor-security`
3. **模型供应链中毒** `model-supply-chain-poisoning`

原因：

- 用户 query 往往不同：
  - “data poisoning defense”
  - “backdoor detection”
  - “poisoned pretrained model”
- 召回邻居也不同：
  - sample sanitization
  - trigger detection / purification
  - transfer learning / merged model / encoder poisoning
- 如果混成一个 family，排序很容易再次塌成最密的 backdoor 子簇

---

## 对 benchmark 的建议（暂不立即落主文件）

### 现有已相对稳定的二级 case

- `llm-jailbreak-security`
- `rag-codegen-security`
- `agentic-llm-security`
- `llm-app-ecosystem-security`
- `model-malware-abuse`

### 建议优先新增的二级 case

1. `prompt-injection-rag-security`
2. `training-data-poisoning-security`
3. `model-backdoor-security`
4. `llm-backdoor-security`
5. `training-data-extraction-security`
6. `prompt-ip-leakage-security`

其中优先级最高的是：

- `prompt-injection-rag-security`
- `model-backdoor-security`
- `training-data-poisoning-security`

因为这三条最能把 `ai-security` 从“LLM jailbreak/RAG”扩到更完整的 AI 安全版图。

---

## 对 runtime profile 的建议

当前 `ai-security` runtime profile 继续保留 broad aggregate 是合理的，但用途应明确为：

- broad generic query 的兜底识别
- 子族 query 的 parser / expansion / prototype seed 辅助
- 诊断 umbrella-level neighbor drift

不建议再指望仅靠一个 broad profile，把所有二级子族都排到很理想。

更合理的方向：

- broad `ai-security`：保留 umbrella profile
- 二级 family query：逐步补 family-aware benchmark 与更细粒度 prototype / anchor terms
- 在 profile 中逐步加入：
  - poisoning / backdoor
  - extraction / privacy leakage
  - watermark / ownership
  - prompt IP / adapter supply chain

---

## 下一步最推荐动作

### P1. 先补 `prompt-injection-rag-security` benchmark case

这是当前最直接的缺口。

### P2. 再补 `model-backdoor-security` 与 `training-data-poisoning-security` 两个 benchmark case

这样 `ai-security` 的版图就不再只偏 LLM 交互期安全，而是把训练期攻击/防御也纳入稳定观察面。

### P3. 如果继续扩 profile，优先给 `ai-security` 增加 poisoning/backdoor/extraction/watermark 相关 prototype clusters

否则 broad `ai-security` 很容易继续被 jailbreak / prompt injection 两簇主导。
