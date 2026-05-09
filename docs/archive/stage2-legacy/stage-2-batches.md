# Stage 2 实施批次

> 只拆 Stage 2，不混入 Stage 1 或 Stage 3。

## Stage 2 目标

把 PaperRadar 从“能抓、能搜、能订阅”的 Stage 1 系统，升级成“能快速阅读、总结、汇报”的 Stage 2 系统。

核心方向：

- HTML 阅读页
- 单篇论文报告
- 主题报告
- PPT 生成
- 报告产物管理

---

## 批次 1：HTML 阅读页基础版

### 目标

把已解析的全文结果转成可浏览的 HTML 阅读页面。

### 本批只做

- 解析结果读取
- HTML 阅读页模板
- 基于 `paper_id` 展示 preview / chunk
- 从前端打开阅读页

### 本批交付物

- reader API
- HTML reader page
- 基础样式模板

### 不做

- 不做复杂高亮
- 不做引用跳转
- 不做图表提取

---

## 批次 2：单篇论文报告生成

### 目标

为单篇论文生成结构化摘要报告。

### 本批只做

- 报告生成脚本
- 单篇报告 JSON / HTML 产物
- 报告基本结构：
  - 摘要
  - 主要贡献
  - 方法概述
  - 结论

### 本批交付物

- report generator
- paper summary template
- report storage

### 不做

- 不做 PPT
- 不做配图
- 不做多篇主题综述

---

## 批次 3：报告查看页

### 目标

让前端能查看单篇报告。

### 本批只做

- 报告详情 API
- 报告前端页面
- 报告列表入口

### 本批交付物

- report API
- report page

### 不做

- 不做分享系统
- 不做导出按钮以外的复杂交互

---

## 批次 4：主题报告（多篇聚合）

### 目标

给定查询或订阅主题，生成多篇论文的聚合报告。

### 本批只做

- 主题报告生成器
- 选取若干论文
- 汇总共同主题 / 差异点 / 趋势

### 本批交付物

- topic report pipeline
- topic report data model

### 不做

- 不做复杂图谱
- 不做自动推送

---

## 批次 5：PPT 生成

### 目标

为单篇或主题报告生成演示文稿。

### 本批只做

- PPT 生成脚本
- 基础模板
- 产物入库

### 本批交付物

- ppt generator
- ppt file storage

### 不做

- 不做自动美化
- 不做复杂动画

---

## 批次 6：报告产物管理与状态流转

### 目标

把 HTML / PPT / 报告状态真正纳入系统。

### 本批只做

- reports 表 / 状态字段落地
- 报告产物管理
- 前后端状态展示

### 本批交付物

- report status api
- report storage model
- frontend status view

---

## 批次 7：Stage 2 收尾与部署

### 目标

把 Stage 2 的阅读与报告能力真正接入当前部署环境。

### 本批只做

- systemd / nginx 适配更新
- 构建与部署校验
- Stage 2 验收文档

### 本批交付物

- deploy updates
- stage2 acceptance doc

---

## 一句话结论

**Stage 2 不应该一口气做成“全自动报告平台”，而应该按“阅读页 → 单篇报告 → 多篇主题报告 → PPT → 状态管理”逐批推进。**
