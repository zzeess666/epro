# M2 策略层 — 开发任务指令

> 供 cursor-agent 执行的开发任务。严格按此文档实现，不偏离范围。

## 目标

在 M1 数据层基础上，实现三个策略（A二次突破 / B缩量回踩 / C综合评分）+ 回溯引擎（胜率计算）。

## 前置条件

- M1 已完成：`daily_kline` 表有数据（100 只，含 ma5/10/20/60）
- `stock_basic` 表有 100 只股票
- 复用 M1 的 `config`、`src/db/connection.py`、`src/api/mairui_client.py`

## 新增数据库表（追加到 sql/schema.sql）

```sql
CREATE TABLE IF NOT EXISTS strategy_signal (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  dm VARCHAR(10) NOT NULL,
  t DATE NOT NULL,
  strategy VARCHAR(10) NOT NULL COMMENT 'A/B/C',
  score DECIMAL(10,2),
  entry_price DECIMAL(10,2),
  stop_loss DECIMAL(10,2),
  detail TEXT COMMENT 'JSON 信号详情',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_dm_t (dm, t)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS backtest_result (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  strategy VARCHAR(10) NOT NULL,
  start_date DATE,
  end_date DATE,
  hold_days INT,
  sample_count INT,
  win_count INT,
  win_rate DECIMAL(5,2),
  avg_return DECIMAL(10,2),
  avg_loss DECIMAL(10,2),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

## 新增文件结构

```
src/strategy/
  __init__.py
  base_strategy.py      # 策略基类：统一 signal 输出接口
  strategy_a.py         # 二次突破
  strategy_b.py         # 缩量回踩
  strategy_c.py         # 综合评分
src/backtest/
  __init__.py
  backtest_engine.py    # 回溯引擎
scripts/
  run_strategy.py       # CLI：跑策略生成信号
  run_backtest.py       # CLI：回溯计算胜率
```

## 策略算法（核心）

### 策略A：二次突破（参考 E8 FalgbreakCalculator）

输入：某只股票的日K序列（日期升序，含 o/h/l/c/v/ma5）。

对"今日"判断是否触发：
1. 需要 ≥ 31 根K线
2. 今日收盘价 > 前 5 天内某日（记 bRow）的最高价
3. 今日"突破强度" > 30（收盘价连续 30 天高于更早的K线高点）
4. bRow 那天的"突破强度" > 30（即首次突破 30 日新高）
5. 中间回调质量检查（bRow 到今日之间）：
   - 中间每天最高价 < bRow 最高价（不破首次突破高点）
   - 中间每天收盘价 ∈ [0.95×bRow收盘, bRow收盘]（缩量回调不破低）
   - 中间每天成交量 ≤ 1.1×今日成交量（缩量确认）
   - 中间每天收盘价 > ma5（保持强势）

**突破强度**：从某日往前数，收盘价连续高于更早K线最高价的天数（遇不满足即停止）。

**止损**：bRow 那天的低点。
**建议买入价**：今日收盘价。

### 策略B：缩量回踩

输入同上。对"今日"判断：
1. 需要 ≥ 20 根K线
2. 趋势向上：今日 ma5 > ma10 > ma20
3. 今日收盘价回踩到 ma10 或 ma20 附近（|收盘 - ma10| ≤ 3% 或 |收盘 - ma20| ≤ 3%）
4. 今日成交量 ≤ 前 5 日均量的 60%（缩量）
5. 今日止跌信号：收盘价 ≥ 开盘价（小阳线）或 下影线长度 > 0（最低价 < 收盘价，有承接）

**止损**：ma20 值。
**建议买入价**：今日收盘价。

### 策略C：综合评分（MVP 版，先本地维度）

M2 阶段只实现**本地可算的两个维度**，估值/利润维度留 TODO（后续补外部数据）：

| 维度 | 权重 | 打分逻辑（0-100）|
|------|------|-----------------|
| 技术形态 | 50% | ma5>ma10>ma20 多头 +30；今日收>ma5 +20；近5日涨幅3%-7% +30；量比>1.5 +20 |
| 资金活跃 | 50% | 今日量 > 5日均量1.2倍 +40；换手率/量能温和放大 +30；无长上影 +30 |

评分 ≥ 60 分才算"命中"，进入候选。

## 回溯引擎（backtest_engine.py）

对每个策略，遍历所有股票的历史K线：

1. 按日期升序遍历，逐日判断是否触发策略信号
2. 触发时记录：`entry_price`（当日收盘）、`stop_loss`（策略定义）
3. 模拟持有 `hold_days`（默认 5）个交易日：
   - 若期间最低价跌破 `stop_loss` → 记为亏损（亏损幅度 = 止损价相对买入价的跌幅，通常约 -4%）
   - 否则持有满 N 天，按第 N 天收盘价算收益
4. 收益 > 0 记为盈利，否则亏损
5. 统计：样本数、盈利次数、胜率、平均收益、平均亏损

**注意**：回溯只读历史数据，不调麦蕊接口，纯本地计算。

## CLI 入口

- `python scripts/run_strategy.py --strategy A` 跑单策略（默认跑 A/B/C 全部）
- `python scripts/run_backtest.py --strategy A --hold-days 5` 回溯单策略（默认全部，hold=5）
- 结果写入 strategy_signal / backtest_result 表

## 验收标准（M2 完成必须满足）

1. `python scripts/run_strategy.py` 后，strategy_signal 有信号数据，覆盖 A/B/C 三策略
2. `python scripts/run_backtest.py` 后，backtest_result 有三策略的胜率数据
3. 回溯样本数 ≥ 10（100 只 × 120 天应能产生足够信号）
4. 策略A/B 逻辑与上述算法一致，策略C 评分有明确规则
5. 止损价正确写入信号

## 禁止事项

- ❌ 禁止调麦蕊 MA/MACD 接口（用 M1 已算好的本地数据）
- ❌ 禁止全量同步（保持 ≤100 只）
- ❌ 禁止实现 Web / 推荐排序 / 跟踪（那是 M3/M4）
- ❌ 策略C 禁止在 M2 调财务接口（估值/利润维度留 TODO）
- ❌ 禁止 git commit/push（架构师验收后统一提交）
