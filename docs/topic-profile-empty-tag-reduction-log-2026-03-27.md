# Topic Profile 空 Tag 压降记录（2026-03-27）

更新日期：2026-03-27 07:33 (Asia/Shanghai)

## 本轮目标

不是继续补全缺失 profile 主链路，而是针对已经生成但 `topic_tags = []` 的样本，降低空 tag 数量。

## 起始状态

在全量 backfill 完成后，库内状态约为：

- 总论文：`1237`
- 已有 topic profile：`1231`
- 缺失 profile：`6`
- 空 tag：`168`

结论：

- `missing_profiles` 已基本补完
- 主要矛盾转为 `empty_tags`

## 原因判断

抽样检查空 tag 样本后，确认主因不是失败 run，而是：

- `status = success`
- `finish_reason = STOP`
- 但模型直接返回：

```json
{"topic_tags": [], "topic_summary": "..."}
```

因此空 tag 的主要根因是：

1. taxonomy 覆盖不够宽
2. prompt 过于保守（倾向于返回空数组）
3. fallback 只对部分主题有效，粗粒度兜底不足

## 本轮改动

### 1. 放宽 topic profile prompt 策略

在 `app/scripts/topic_profile_lib.py` 中，把规则从：

- 没有特别合适主题时返回 `[]`

调整为：

- 优先选择最接近的高层安全主题
- 只有明显不属于 security/privacy/trust/safety/governance 时才返回 `[]`

### 2. 扩展 taxonomy

本轮新增 / 强化的 canonical topic 包括：

- `network security`
- `systems security`
- `cyber-physical security`
- `trusted execution security`
- `abuse and fraud detection`
- `usable security`
- `iot security`
- `ransomware`
- `internet measurement`
- `hardware attacks`
- `media authenticity and deepfakes`
- `blockchain security`
- `content moderation and platform integrity`
- `privacy and security behavior`
- `ai model integrity and watermarking`

### 3. 扩展 fallback 粗规则

在 `topic_profile_lib.py` 中补充了粗粒度关键词兜底，覆盖例如：

- enclave / TEE / SGX / confidential computing
- kernel / privilege / isolation / compartmentalization
- BGP / routing / PROXY protocol / internet scanning / measurement study
- LiDAR / EMI / signal injection / radar / wireless jamming
- scam / fraud / blocklist / harmful meme / domain squatting
- password / accessibility / password manager
- ransomware / extortion / ransom note
- IoT / device identification
- blockchain / consensus / staking
- watermark / attribution / training integrity / inference integrity
- smartphone theft / privacy concerns / recovery behavior

## 实际执行的修复批次

### 第一轮试刷

```bash
python3 app/scripts/topic_profile_maintenance.py empty_tags 20
```

结果：有改善，但仍有较多样本继续空 tag。

### 第二轮

```bash
python3 app/scripts/topic_profile_maintenance.py empty_tags 50
```

结果：明显下降，taxonomy 扩展开始系统性生效。

### 第三轮

```bash
python3 app/scripts/topic_profile_maintenance.py empty_tags 100
```

结果：继续显著下降。

## 典型被救回的样本类型

本轮新增标签成功覆盖的方向包括：

- `trusted execution security`
- `systems security`
- `network security`
- `internet measurement`
- `cyber-physical security`
- `wireless jamming`
- `electromagnetic interference`
- `ransomware`
- `usable security`
- `iot security`
- `abuse and fraud detection`
- `content moderation and platform integrity`
- `privacy and security behavior`
- `media authenticity and deepfakes`

## 当前收尾状态

截至 2026-03-27 07:26 左右，数据库状态为：

- 总论文：`1237`
- 已有 topic profile：`1231`
- 缺失 profile：`6`
- 空 tag：`42`
- `MAX_TOKENS` runs：`45`

### 空 tag 压降效果

- 初始：`168`
- 中间：`115`
- 当前：`42`

净减少：`126`

## 当前剩余问题

### 1. 还剩 42 条空 tag

按 venue 分布：

- `NDSS`: 18
- `USENIX_SECURITY`: 14
- `IEEE_SP`: 9
- `ACM_CCS`: 1

这些剩余样本更可能是：

- 更边缘 / 交叉型主题
- taxonomy 仍不够贴
- 少量本身不适合强打安全标签的论文

### 2. 还剩 6 条 missing profile

这个数量已经很小，可后续单独修。

### 3. `MAX_TOKENS` 仍有 45 条

这部分建议后续按 `max_tokens` 单独做低频修复，不要再和空 tag 问题混在一起处理。

## 建议的后续顺序

如果后续继续推进，建议顺序改为：

1. 抽样看剩余 42 条空 tag，决定是否还要补最后一两个桶
2. 单独补 6 条 missing
3. 单独跑 `max_tokens` 修复

不建议：

- 继续无脑全量重刷所有 empty tags
- 在 taxonomy 中无限加标签而不抽样验证

因为当前已经进入收尾阶段，继续粗暴扩张会带来过标注和噪音标签风险。
