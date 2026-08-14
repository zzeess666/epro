# M5 动态指标组合 — 开发任务指令

> 供 cursor-agent 执行的开发任务。严格按此文档 + docs/STRATEGY_DESIGN.md 实现。

## 目标

重构策略层为「动态指标组合」：因子库计算 → 自动组合 → 分周期回溯 → 胜率排行 → 动态选股。核心是**防过拟合**（训练/测试分离）。

## 前置条件

- 全历史数据已就绪：daily_kline 约1123万条，5209只（仅沪深，无北交所）
- 复用 config、src/db、src/api

## 核心设计（务必遵守）

### 防过拟合（最高优先级）
历史数据按时间分成两段：
- **训练期**：前 80% 的交易日
- **测试期**：后 20% 的交易日

组合在训练期挖掘，在测试期验证。**只有训练期和测试期胜率都达标的组合才进入排行**。

## 新增文件结构

```
src/factor/
  __init__.py
  factor_library.py      # 因子库：每天每只股票计算指标（0/1）
src/combo/
  __init__.py
  combination_miner.py   # 组合挖掘：枚举2-3指标组合，分周期回溯
  win_rate_ranker.py     # 胜率排行：训练期+测试期双验证
src/screen/
  __init__.py
  dynamic_screener.py    # 动态选股：用最优组合筛当日股票
scripts/
  run_factor.py          # CLI：计算因子库
  run_miner.py           # CLI：组合挖掘+胜率排行
  run_screen.py          # CLI：动态选股
```

## 1. 因子库（factor_library.py）

为每只股票每天计算指标，输出 0/1 标记。存表 `factor_flag`：

```sql
CREATE TABLE IF NOT EXISTS factor_flag (
  dm VARCHAR(10) NOT NULL,
  t DATE NOT NULL,
  factor VARCHAR(30) NOT NULL COMMENT '指标名',
  flag TINYINT NOT NULL DEFAULT 0 COMMENT '0/1',
  PRIMARY KEY (dm, t, factor)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 用户指定指标（必须实现）
| 指标 | 因子名 | 判断逻辑 |
|------|--------|---------|
| MACD金叉 | `macd_golden` | 今日 diff > dea 且昨日 diff ≤ dea |
| 跳空高开 | `gap_up` | 今日开盘价 > 昨日最高价 |
| 一阳穿三线 | `one_yang_3ma` | 今日阳线，且收盘>MA5>MA10>MA20（或最低<三者且收盘>三者）|

### 架构师补充指标（实现这些，可增减）
| 指标 | 因子名 | 判断逻辑 |
|------|--------|---------|
| 多头排列 | `ma_bull` | MA5>MA10>MA20 |
| 站上MA20 | `above_ma20` | 收盘 > MA20 |
| 5穿10金叉 | `ma5_cross_10` | 今日MA5上穿MA10 |
| 二次突破 | `second_breakout` | 参考原 strategy_a 逻辑 |
| 缩量回踩 | `shrink_pullback` | 量<前5日均量60% 且 收盘贴近MA10/MA20 |
| 量比放大 | `volume_ratio_high` | 量比 > 1.5 |
| 创20日新高 | `new_high_20` | 收盘创20日新高 |
| 涨停 | `limit_up` | 涨幅 ≥ 9.5% |

（MACD 的 diff/dea 需在因子计算时本地算出）

## 2. 组合挖掘（combination_miner.py）

- 从因子库枚举 **2-3 个指标的组合**（如 macd_golden + gap_up + ma_bull）
- 组合数量可控：若因子总数 N，枚举 C(N,2)+C(N,3)
- 对每个组合，回测历史：满足组合所有指标的那天买入，按**4个周期**（3/5/20/60天）分别统计胜率
- 止损按周期：超短2%、短3-4%、中短5-6%、中8%

## 3. 胜率排行（win_rate_ranker.py）

- 每个组合 × 周期，分别算训练期胜率和测试期胜率
- **有效组合**：训练期胜率≥60% 且 测试期胜率≥60% 且 两期样本各≥30
- 输出排行表，存 `combo_rank`：

```sql
CREATE TABLE IF NOT EXISTS combo_rank (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  combo VARCHAR(200) COMMENT '指标组合，如 macd_golden+gap_up',
  period VARCHAR(10) COMMENT '周期标签 超短/短/中短/中',
  hold_days INT,
  train_win_rate DECIMAL(5,2),
  test_win_rate DECIMAL(5,2),
  train_sample INT,
  test_sample INT,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

## 4. 动态选股（dynamic_screener.py）

- 读 combo_rank 当前最优组合（综合训练+测试胜率排序）
- 用该组合的指标条件，筛当日满足的股票
- 输出推荐（TOP 5-10，供人为筛选），每只带：代码、名称、命中组合、周期、建议买入价、止损价（按周期）
- 剔除 ST 和京市（jys != BJ，名称不含 ST）

## CLI

- `python scripts/run_factor.py` → 计算全市场因子，写 factor_flag
- `python scripts/run_miner.py` → 组合挖掘 + 胜率排行，写 combo_rank
- `python scripts/run_screen.py` → 用最优组合筛当日股票，输出推荐

## 验收标准（M5 完成必须满足）

1. `run_factor.py` 后 factor_flag 有数据，覆盖用户指定3指标
2. `run_miner.py` 后 combo_rank 有排行，且只含训练+测试双达标的组合
3. `run_screen.py` 能输出推荐（含止损价、命中组合、周期）
4. 防过拟合生效：训练/测试分离，双验证
5. 剔除 ST 和京市
6. 样本 ≥ 30 门槛生效

## 禁止事项

- ❌ 禁止全量同步（数据已就绪，只做因子/挖掘/选股）
- ❌ 禁止 git commit/push（架构师验收后统一提交）
- ❌ 禁止用未来数据（计算当日因子只能用当日及之前的数据，防未来函数）
- ❌ 因子计算禁止调麦蕊 MA/MACD 接口（用 daily_kline 本地算）
