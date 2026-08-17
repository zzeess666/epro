# M15 回溯界面体验优化 — 开发任务指令

> 供 cursor-agent 执行。纯前端 + 小幅后端，不改核心逻辑。

## 4 个调整

### 1. Tab 固定在页面底部
- 三个 Tab（今日推荐/历史回放/回溯分析）固定到**页面底部**（对齐 e8 的底部 tabbar）
- CSS：`position: fixed; bottom: 0; left: 0; right: 0;` + 底部安全区 padding
- 内容区底部留出 tab 高度，避免被遮挡（body 加 padding-bottom）

### 2. 移除「手动回溯」区域
- 删除因子复选框、周期下拉、回溯按钮、手动回溯结果区
- 回溯分析 Tab 只保留：单选框（收益周期 + 样本范围）+ 组合汇总 + 命中详情 + 单股详情
- 组合由系统自动计算胜率排序（即现有的 /api/bt/summary 结果）

### 3. 内嵌滚动条
- 组合汇总表、命中详情表、单股详情表各自加**内嵌滚动条**
- 表格容器加 `max-height`（如汇总 420px、命中详情 420px、单股详情 300px）+ `overflow-y: auto`
- 表头 sticky 固定（thead 加 `position: sticky; top: 0`）

### 4. 单股详情加日K图片
- 点击股票后，单股详情区显示该股票的日K图片
- 图片地址（新浪，与 e8 一致）：
  ```
  https://image.sinajs.cn/newchart/daily/n/{sh|sz}{6位代码}.gif
  ```
- 前缀判断：6 开头（含688）→ `sh`；其余（0/3开头）→ `sz`
- 例：002322 → `sz002322`；600503 → `sh600503`
- 前端加辅助函数 `sinaDailyImg(dm)`，在单股详情顶部显示 `<img>` 标签

## 实现要点

- 单股详情的日K图：前端直接构造 URL，无需后端改动
- 图片加载失败时给个占位提示（onerror 隐藏）
- 保持组合名中文映射（comboCn / FACTOR_CN）

## 验收标准

1. Tab 固定在底部，切换正常
2. 回溯分析 Tab 无手动回溯，只有单选框 + 三段式
3. 汇总/命中/单股三张表有内嵌滚动条，表头 sticky
4. 点击股票后单股详情显示新浪日K图

## 禁止事项

- ❌ 不改后端 API 逻辑（bt/summary、bt/group、bt/stock 不动）
- ❌ 不 git commit/push
