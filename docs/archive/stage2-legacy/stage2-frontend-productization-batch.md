# Stage 2 / Frontend Productization Batch

## 目标

在不推翻现有 Next.js 结构的前提下，把 PaperRadar 前端从“调试页集合”升级为可持续扩展的研究工作台，并更好展示 Stage 1 已完成功能。

## 本批实现

### 技术栈

- 保留 Next.js
- 接入 Tailwind CSS
- 新增轻量基础组件层（layout / card / badge / button / input）
- 新增 lucide-react 图标与通用工具函数

### 页面结构升级

- 新增统一工作台布局：侧边导航 + 顶部标题区 + 内容区
- 首页重做为 Dashboard：
  - Stage 1 状态概览
  - 支持会议与链路能力卡片
  - Stage 2 下一步展示
- Search 页面重做：
  - 统一卡片布局
  - 搜索结果更清晰展示论文状态与操作入口
- Subscriptions 页面重做：
  - 订阅创建表单
  - 活跃订阅列表
  - 手动执行匹配入口
- Fulltext Tools 页面重做：
  - 以工作台风格展示全文抓取 / 解析 / 阅读入口
- Reader 页面升级：
  - 统一视觉风格
  - 阅读预览 / chunk 预览 / 状态信息

## 验证

```bash
cd /opt/paperradar/app/frontend
npm run build
```

预期：构建通过。

## 当前未做

- 尚未正式接入 shadcn/ui 完整组件体系
- 尚未增加 system status 独立页面
- 尚未引入 report / topic report / PPT 页面
- 尚未做深色模式与更复杂的交互状态管理

## 下一步建议

优先继续：

1. 补一个 `System / Status` 页面，展示 Stage 1 运行状态
2. 然后进入 Stage 2 Batch 2：单篇论文报告生成器
