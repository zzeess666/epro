# M16 当日信号 Tab — 开发任务指令

> 供 cursor-agent 执行。新增「当日信号」Tab，回溯分析点组合名查看该组合最新交易日筛出的股票。

## 目标

1. 底部新增「当日信号」Tab（今日推荐/当日信号/历史回放/回溯分析 共4个）
2. 回溯分析里，组合名做成可点击链接，点击跳转「当日信号」Tab
3. 当日信号 Tab 显示该组合在最新交易日筛出的股票（列表 + 日K图 + 买入/止损价）

## 1. 后端 API（src/web/app.py）

### GET /api/signal?combo=box_breakout+expma_golden+gap_up
返回该组合在**最新交易日**筛出的股票：

```json
{"combo":"...","date":"2026-08-14","list":[
  {"dm":"002322","mc":"理工能科","close":13.05,"pct_change":7.5,"entry":13.05,"stop":12.01}
]}
```

逻辑：
1. combo 用 `+` 拆成因子列表
2. 最新交易日 = MAX(t) from daily_kline
3. 查该日同时命中所有因子的股票：
   ```sql
   SELECT dm FROM factor_flag
   WHERE t = :latest AND flag = 1 AND factor IN (...)
   GROUP BY dm HAVING COUNT(DISTINCT factor) = :n
   ```
4. 每只股票：mc（stock_basic）、close（当日收盘）、pct_change（相对前一交易日收盘）、entry=close、stop=round(close×0.92,2)
5. 按 pct_change 降序或按代码排序

## 2. 前端（public/index.html）

### 新增「当日信号」Tab
- 底部 Tab 增加「当日信号」（4个 tab）
- 内容：顶部显示组合名（中文）+ 日期，下方股票列表
- 每只股票显示：代码、名称、现价、涨幅、建议买入价、止损价、日K图（sinaDailyImg）

### 回溯分析组合汇总表交互
- 组合名那一格做成可点击链接（蓝色，下划线）
- 点击组合名 → 记录 combo 到全局变量，切换到「当日信号」Tab，调 /api/signal 加载
- 点击行其他部分 → 保持现有命中详情逻辑（不跳转）

## 3. 复用

- 日K图：复用 M15 的 sinaDailyImg(dm)（`https://image.sinajs.cn/newchart/daily/n/{sh|sz}{dm}.gif`）
- 组合中文：复用 comboCn / FACTOR_CN
- 现有底部 Tab 结构、样式

## 验收标准

1. 底部4个 Tab，当日信号可切换
2. 回溯分析点组合名跳当日信号，显示该组合最新交易日股票
3. 每只股票含：代码/名称/现价/涨幅/买入价/止损价/日K图
4. 点击行其他部分仍是命中详情

## 禁止事项

- ❌ 不改回溯 API（bt/summary、bt/group、bt/stock）
- ❌ 不 git commit/push
- ❌ 当日信号数据从 factor_flag 查，不调麦蕊实时接口（用库内数据）
