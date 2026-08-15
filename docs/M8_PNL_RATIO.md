# M8 盈亏比评估 — 开发任务指令

> 供 cursor-agent 执行。核心：评估标准从「胜率≥60%」改为「期望收益为正 + 盈亏比达标」。

## 背景

诊断确认：样本充足的组合，测试期胜率最高仅51%，达不到60%。但盈亏比可达1.6-1.8，期望收益为正。因此改为盈亏比模式：小止损博大盈利。

## 目标

1. 组合挖掘统计「均盈、均亏、盈亏比、期望收益」
2. 排行标准改为「期望收益为正 + 盈亏比>1.2」
3. combo_rank 表增加相关字段

## 1. ComboPeriodStats 扩展（combination_miner.py）

在现有 `train_wins/train_n/test_wins/test_n` 基础上，新增：
- `train_win_pnl` / `train_loss_pnl`：盈利样本收益总和 / 亏损样本收益总和
- `test_win_pnl` / `test_loss_pnl`：同上（测试期）

`add(ret, is_train)` 里累计：ret>0 记入 win_pnl，否则记入 loss_pnl。

新增属性（训练/测试各一套）：
- `avg_win`：win_pnl / wins
- `avg_loss`：loss_pnl / (n - wins)
- `profit_ratio`：avg_win / |avg_loss|
- `expectation`：胜率×avg_win - (1-胜率)×|avg_loss|

## 2. combo_rank 表追加字段

```sql
ALTER TABLE combo_rank ADD COLUMN train_avg_win DECIMAL(10,2);
ALTER TABLE combo_rank ADD COLUMN train_avg_loss DECIMAL(10,2);
ALTER TABLE combo_rank ADD COLUMN test_avg_win DECIMAL(10,2);
ALTER TABLE combo_rank ADD COLUMN test_avg_loss DECIMAL(10,2);
ALTER TABLE combo_rank ADD COLUMN train_ratio DECIMAL(10,2);
ALTER TABLE combo_rank ADD COLUMN test_ratio DECIMAL(10,2);
ALTER TABLE combo_rank ADD COLUMN train_expectation DECIMAL(10,4);
ALTER TABLE combo_rank ADD COLUMN test_expectation DECIMAL(10,4);
```
（schema.sql 里同步加，且运行时可 ALTER 兼容旧表）

## 3. 排行标准（win_rate_ranker.py）

`is_valid(row)` 改为：
```python
训练期：train_n ≥ 25 且 train_expectation > 0 且 train_ratio ≥ 1.2
测试期：test_n ≥ 25 且 test_expectation > 0 且 test_ratio ≥ 1.2
```

排序 `rank_valid` 改为按「测试期期望收益 + 训练期期望收益」综合降序。

## 4. 输出

排名输出每行增加：均盈/均亏/盈亏比/期望收益。

## 验收标准

1. 重跑后 combo_rank 有「期望收益为正 + 盈亏比≥1.2」的组合
2. 排名按期望收益排序，不是纯胜率
3. 均盈、均亏、盈亏比、期望收益字段正确写入
4. 样本门槛 25 生效

## 禁止事项

- ❌ 不改因子库、回踩买入、大盘过滤逻辑（只改统计和评估）
- ❌ 不 git commit/push
- ❌ 期望收益公式：胜率×均盈 - (1-胜率)×|均亏|
