# M3 评分风控 — 开发任务指令

> 供 cursor-agent 执行的开发任务。严格按此文档实现。

## 目标

在 M2 策略基础上，实现风控过滤 + 统一评分排序 + TOP3 推荐，并对策略调优以提升胜率。

## 前置条件

- M1/M2 已完成，strategy_signal 有 A/B/C 信号数据
- stock_basic 有 100 只股票（含 mc 名称，用于排除 ST）

## 新增数据库表（追加 sql/schema.sql）

```sql
CREATE TABLE IF NOT EXISTS recommend_result (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  t DATE NOT NULL COMMENT '推荐日期',
  dm VARCHAR(10) NOT NULL,
  strategy VARCHAR(10) COMMENT '命中策略',
  score DECIMAL(10,2) COMMENT '综合评分',
  reason TEXT COMMENT '推荐理由',
  entry_price DECIMAL(10,2),
  stop_loss DECIMAL(10,2),
  position_pct DECIMAL(5,2) COMMENT '建议仓位',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_t (t)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

## 新增文件

```
src/risk/
  __init__.py
  risk_filter.py       # 风控过滤（四铁律）
src/recommend/
  __init__.py
  recommend_engine.py  # 统一评分 + 排序 + TOP3
scripts/
  run_recommend.py     # CLI：生成每日推荐
```

## 1. 风控过滤（risk_filter.py，一票否决）

对每个信号，满足以下**任一**则过滤掉：

| # | 风控规则 | 判断 |
|---|---------|------|
| 1 | 最大亏损 ≤ 4% | `(entry_price - stop_loss) / entry_price > 4%` → 过滤 |
| 2 | 排除 ST | `mc` 名称含 `ST` / `*ST` / `退` → 过滤 |
| 3 | 流通市值 20-500 亿 | 市值不在区间 → 过滤 |
| 4 | PE < 50 | PE ≥ 50 或为负/空 → 过滤 |
| 5 | PB < 5 | PB ≥ 5 → 过滤 |

**市值/PE/PB 数据来源**：候选股调用麦蕊实时行情 `/hsrl/ssjy/{dm}/{licence}`，取 `lt`(流通市值)、`pe`、`sjl`(市净率)，并回写 stock_basic（ltsz/pe/pb）。候选股通常几十只，额度可控。

**注意**：PE/PB 为负或空时，保守处理为「过滤」（不符合稳健原则）。

## 2. 策略调优（提升胜率）

### 策略C 门槛提高
- 入选门槛 60 分 → **75 分**（减少弱信号）

### 策略A 止损收紧
- 止损价 = `max(首次突破日低点, 买入价 × 0.96)`（确保最大亏损 ≤ 4%）

### 策略B 微调
- 缩量条件：今日量 ≤ 前 5 日均量 **50%**（原 60%，更严格）
- 回踩幅度收紧到 |收盘 - ma10| ≤ 2%

## 3. 推荐引擎（recommend_engine.py）

1. 读取当日（最新交易日）三策略信号
2. 风控过滤（risk_filter）
3. 统一评分：策略C 用自身评分；策略A/B 给固定基础分（A=70，B=65，可按命中质量微调）
4. 按评分降序，取 **TOP3**
5. 写入 recommend_result，每只含：评分、命中策略、推荐理由（模板）、建议买入价、止损价、建议仓位（默认 10%）

**推荐理由模板**：
- 策略A：「二次突破形态，评分 X 分，止损 Y 元」
- 策略B：「缩量回踩支撑，评分 X 分，止损 Y 元」
- 策略C：「综合评分 X 分，技术形态与资金活跃度达标」

## 4. 重新回溯验证

风控 + 调优后，重新跑 `run_backtest.py`，观察胜率是否提升。验收标准见下。

## CLI 入口

- `python scripts/run_recommend.py` → 生成当日 TOP3 推荐，写入 recommend_result

## 验收标准（M3 完成必须满足）

1. `python scripts/run_recommend.py` 后，recommend_result 有 ≤ 3 条推荐
2. 每推荐含止损价，且 (entry - stop)/entry ≤ 4%
3. 推荐股票的市值/PE/PB 符合风控要求
4. ST 股被排除
5. 策略C 信号数明显下降（门槛 60→75 后应减少）
6. 风控后回溯胜率较 M2 有所提升（目标：至少一个策略 ≥ 50%，B 策略冲击 60%）

## 禁止事项

- ❌ 禁止全量同步（≤100 只）
- ❌ 禁止 git commit/push（架构师验收后统一提交）
- ❌ 禁止实现 Web 页面 / 盘中跟踪（M4）
- ❌ PE/PB 为负时禁止放行（保守过滤）
