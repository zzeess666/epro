# M12 交互式回溯界面 — 开发任务指令

> 供 cursor-agent 执行。核心：网页提供「组合胜率排行」+「手动回溯」交互，对齐 e8 回溯体验。

## 目标

用户能像用 e8 一样：
1. 看到所有组合的胜率排行（可排序）
2. 手动勾选因子组合 → 回溯 → 看该组合的胜率、期望收益、筛选出的股票

## 1. 后端 API（src/web/app.py 增加）

### GET /api/combos
返回 combo_rank 全量（达标组合的胜率排行）：
```json
{"combos": [
  {"combo":"box_breakout+expma_golden+gap_up","period":"中短","test_win_rate":68.72,"test_expectation":7.12,"test_ratio":2.07,"test_sample":1397,"train_win_rate":35.4}
]}
```

### GET /api/backtest?factors=a,b,c&period=短
手动回溯任意因子组合（2-3个因子），实时计算：
- 复用 combination_miner 的 `_find_pullback_entry`（回踩买入）+ 大盘过滤 + 止损8%
- 只算指定这一个组合（不枚举全部）
- 返回：胜率、期望收益、盈亏比、样本数 + 测试期历史记录列表（买入日/代码/名称/买入价/止损/收益）

```json
{"combo":"a+b+c","period":"短","test_win_rate":...,"test_expectation":...,"records":[...]}
```

注意：实时回溯遍历全市场约数分钟，返回时可设 limit 限制记录数。

## 2. 前端（public/index.html 增加）

### 区域A：组合胜率排行
- 表格展示 /api/combos 的组合（可点击表头排序：胜率/期望/盈亏比/样本）
- 默认按测试胜率降序，展示 TOP 20

### 区域B：手动回溯
- 14 个因子复选框（macd_golden/gap_up/one_yang_3ma/ma_bull/above_ma20/ma5_cross_10/second_breakout/shrink_pullback/volume_ratio_high/new_high_20/limit_up/expma_golden/box_breakout/kline_reversal）
- 周期下拉（超短/短/中短/中）
- 「回溯」按钮 → 调 /api/backtest → 显示胜率/期望/样本
- 结果表格：筛出的股票（买入日/代码/名称/买入价/止损/收益），点击看K线（复用现有K线逻辑）

## 3. 复用现有能力

- 因子列表从 /api/combos 或硬编码14个因子名
- K线图复用现有 renderKline（已支持按需加载 /api/kline）
- 组合名与因子映射：combo 字段是 `+` 分隔的因子名

## 验收标准

1. /api/combos 返回547组合胜率
2. /api/backtest?factors=box_breakout,expma_golden,gap_up&period=中短 返回该组合胜率68.72% + 历史记录
3. 网页：组合排行表可排序，手动勾选因子回溯能出结果
4. 回溯结果点击能看K线

## 禁止事项

- ❌ 不改因子库、组合挖掘、大盘过滤、盈亏比评估核心逻辑
- ❌ 不 git commit/push
- ❌ 手动回溯实时计算别用未来数据
