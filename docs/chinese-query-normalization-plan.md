# 中文 Query Normalization 整理说明

更新日期：2026-03-26

## 这次整理做了什么

把原来散落在 `chat_parser.py` 里的中文 query 清洗逻辑，抽成独立模块：

- `app/backend/query_normalization.py`

并补了专门的中文回归检查：

- `docs/chinese-query-normalization-regression.json`
- `app/scripts/check_chinese_query_normalization.py`

---

## 目标

解决两类问题：

1. **术语被误裁切**
   - 例如：`中毒攻击 -> 毒攻击`
2. **中文结构噪音没有系统处理**
   - 例如：
     - `帮我找提示注入攻击的论文`
     - `同态加密方向的论文`
     - `隐私计算方面的研究`

---

## 当前设计原则

### 1. 术语保真优先

不要为了去噪而删单字中文字符。

尤其不能全局删除：

- `中`
- `里`
- `的`

否则很容易误伤真实术语：

- `中毒攻击`
- `工作窃取`
- `代理的越狱攻击`

### 2. 清理“结构短语”，不清理“词内部字符”

当前只针对明确结构短语做处理，例如：

- 前缀：`关于…` / `对于…` / `有关…`
- 后缀：`的论文` / `的文章` / `的研究` / `方面的研究` / `方向的论文` / `相关工作`

### 3. parser / search 分层清晰

- `query_normalization.py`：负责 query 文本归一化
- `chat_parser.py`：负责 topic / must_terms / should_terms 生成
- `search.py`：负责检索和 rerank，不再承担 query 清洗职责

---

## 新增回归样例

当前回归集中覆盖：

- 中毒攻击
- 提示注入攻击
- 零知识证明
- 安全多方计算
- 浏览器中的指纹攻击
- 同态加密方向的论文
- 隐私计算方面的研究
- AI 安全
- LLM 安全

运行方式：

```bash
python3 app/scripts/check_chinese_query_normalization.py
```

---

## 后续建议

下一步如果继续做，可以按这个顺序：

1. 扩充中文 regression case
   - 后门攻击
   - 越狱攻击
   - 供应链攻击
   - 成员推断攻击
   - 数据投毒攻击
   - 模型窃取攻击
2. 把 query normalization 的结果纳入 benchmark
3. 再考虑是否做更细的中文安全术语词典

当前不建议：

- 再把更多单字直接塞进 stop phrases
- 用激进删词方式追求“更短 topic”

因为这很容易再次引入术语误伤。
