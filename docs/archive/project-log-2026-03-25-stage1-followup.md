# PaperRadar 项目日志 - 2026-03-25（Stage 1 抓取补完 / 搜索主链路迁移）

## 今日完成

### 1. GitHub 私有仓库
- 已创建并推送：`SmallSpider0/PaperRadar`

### 2. Stage 2 / Batch 1
- 已完成 HTML 阅读页基础版
- 包含：reader API、阅读页、搜索页进入阅读页入口
- 提交：`8fe4e36 feat(stage2-batch1): add html reader page and reader api`

### 3. 前端产品化重构
- 已接入 Tailwind（后续修正为 v3 稳定链路）
- 已重做 Dashboard / Search / Subscriptions / Fulltext Tools / Reader
- 新增 System / Status 页面
- 提交：
  - `75a3cb5 feat(frontend): productize stage1 workspace ui`
  - `298bd01 feat(frontend): add system status workspace page`
  - `806bdc7 fix(frontend): restore tailwind styles with v3 pipeline`

### 4. Stage 1 抓取补完 - IEEE S&P
- 已新增 `IEEE S&P 2025 metadata-only crawler`
- 提交：`596649f feat(stage1): add IEEE S&P 2025 metadata crawler`

### 5. IEEE S&P 摘要补全能力
- 已新增 OpenAlex 增强器与分批补全脚本
- 提交：`c404e3a feat(stage1): add IEEE S&P abstract enrichment via OpenAlex`

### 6. 论文主链路切到 PostgreSQL
- 已新增 `ingest_papers_to_postgres.py`
- 搜索已改为：**PostgreSQL 优先，JSON fallback**
- 本地实测：`ingested papers: 921` / `postgres_records = 921`
- 提交：`4f7f944 feat(stage1): move paper search primary path to postgres`

### 7. Metadata embedding
- `build_metadata_embeddings.py` 已跑完
- 输出显示：
  - `embedded ndss_2025_normalized.json: 211`
  - `embedded ieee_sp_2025_normalized.json: 255`
  - `embedded usenix_security_2025_normalized.json: 455`

## 当前未完成 / 下一次会话继续

### A. 在后台继续补完 IEEE S&P 摘要
当前状态：
- 总数：255
- 已有摘要：221
- 已有作者：223
- `data/generated/ieee_sp_2025_enrich_state.json` 当前为：
  - `next_index = 40`
  - `finished = false`

注意：状态文件的 `next_index=40` 与当前已补 221 条不完全一致，说明之前有中断/重复跑过。**下次继续时不要盲信 state 文件，要先按实际文件统计缺失项，再从缺失项继续补。**

### B. embedding 跑完后，需要重新同步到 PostgreSQL
因为 embedding 在 `4f7f944` 之后才跑完，所以需要再执行一次：

```bash
cd /opt/paperradar/app
PYTHONPATH=. python3 scripts/ingest_papers_to_postgres.py
```

目的：把最新 embedding 和后续补到的 IEEE S&P 摘要一起同步入库。

### C. 用户执行部署后，需要复测前端搜索
用户需要在线上执行：

```bash
cd /opt/paperradar/app/frontend
npm run build
sudo systemctl restart paperradar-api.service
sudo systemctl restart paperradar-web.service
```

然后验证：
- `https://example.com/paperradar`
- 搜索页是否能搜出结果
- 二级页面是否正常

## 下一次优先顺序

1. 后台继续补齐 IEEE S&P 缺失摘要
2. 再跑一次 `ingest_papers_to_postgres.py`
3. 用户部署后复测前端搜索
4. 若稳定，再继续 Stage 2 Batch 2：单篇论文报告生成器
