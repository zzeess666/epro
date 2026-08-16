# M13 Tab页 + 因子中文备注 — 开发任务指令

> 供 cursor-agent 执行。纯前端改造，不改后端。

## 目标

1. 页面模块改为 Tab 页切换（当前是纵向堆叠）
2. 因子加中文备注，组合显示中文

## 1. Tab 页结构

三个 Tab：
- **今日推荐**：推荐表格 + 跟踪状态
- **历史回放**：最优组合历史记录 + K线图
- **回溯分析**：组合胜率排行 + 手动回溯

实现：顶部 tab 按钮切换，点击显示对应区域（display 控制），默认「今日推荐」。

## 2. 因子中文映射（前端 JS 常量）

```javascript
var FACTOR_CN = {
  "macd_golden": "MACD金叉",
  "gap_up": "跳空高开",
  "one_yang_3ma": "一阳穿三线",
  "ma_bull": "多头排列",
  "above_ma20": "站上20日线",
  "ma5_cross_10": "5日穿10日",
  "second_breakout": "二次突破",
  "shrink_pullback": "缩量回调",
  "volume_ratio_high": "放量突破",
  "new_high_20": "创20日新高",
  "limit_up": "涨停",
  "expma_golden": "EXPMA金叉",
  "box_breakout": "箱体突破",
  "kline_reversal": "K线反转"
};
```

## 3. 应用中文

- **手动回溯**：14个因子复选框显示中文（如「箱体突破」），value 仍是英文因子名
- **组合排行表**：combo 字段（如 "box_breakout+expma_golden+gap_up"）拆成 `+`，每段用 FACTOR_CN 映射，显示为「箱体突破+EXPMA金叉+跳空」
- **历史回放 meta**：组合名同样转中文
- 加一个 `comboCn(combo)` 辅助函数

## 4. 样式

- Tab 按钮：顶部横向排列，选中高亮
- 各 tab 内容区：`display:none` 切换
- 保持现有表格和K线样式

## 验收标准

1. 三个 Tab 可切换，默认「今日推荐」
2. 因子复选框显示中文
3. 组合排行、手动回溯、历史回放里的组合名显示中文
4. K线图功能正常（切到历史回放 tab 后点击行仍能看K线）

## 禁止事项

- ❌ 不改后端 API、因子库、挖掘逻辑
- ❌ 不 git commit/push
