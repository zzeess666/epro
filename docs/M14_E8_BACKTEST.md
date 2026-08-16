# M14 e8式三段回溯界面 — 开发任务指令

> 供 cursor-agent 执行。完全对齐 e8 回溯界面逻辑：单选框筛选 + 三段式（汇总→组详情→单股详情）。

## 目标

实现 e8 式回溯分析：
1. 单选框选「收益周期」和「样本范围」，得到组合胜率排序
2. 点击组合 → 该组合在范围内满足的股票和时间
3. 点击股票 → 该股票满足的时间和收益

## 口径（已与用户确认）

- **收益周期**：1/2/3/5/7/20/60 个交易日（7档单选框）
- **样本范围**：3/7/15/30/60 自然日（5档单选框）
- **买入口径**：满足日收盘买入，**无止损**（对齐 e8，不用回踩买入）
- **满足日**：某天某股票命中组合所有因子（flag=1）
- **收益第N日** = 满足日后第 N 个交易日的收盘价；收益 = (目标日收盘 - 满足日收盘)/满足日收盘×100
- **组合范围**：只统计达标组合（combo_rank 表里的547个）

## 1. 数据表 bt_satisfy

```sql
CREATE TABLE IF NOT EXISTS bt_satisfy (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  combo VARCHAR(200) NOT NULL COMMENT '组合，如 box_breakout+expma_golden+gap_up',
  dm VARCHAR(10) NOT NULL,
  mc VARCHAR(50),
  buy_date DATE NOT NULL COMMENT '满足日',
  start_price DECIMAL(10,2) COMMENT '满足日收盘',
  day_level INT NOT NULL COMMENT '1/2/3/5/7/20/60',
  end_date DATE COMMENT '目标日',
  end_price DECIMAL(10,2) COMMENT '目标日收盘',
  profit DECIMAL(10,2) COMMENT '收益%',
  UNIQUE KEY uq (combo, dm, buy_date, day_level),
  KEY idx_combo_level (combo, day_level, buy_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

## 2. 预计算脚本 scripts/bt_build.py

遍历全市场，生成所有达标组合的满足记录 + 7周期收益：

1. 读 combo_rank 的达标组合集合（combo 字段去重）
2. 遍历每只股票每天命中的因子集合（factor_flag），生成当天命中的所有2-3因子组合
3. 只保留「在达标组合集合里」的组合
4. 对每个满足日，算 1/2/3/5/7/20/60 各周期的目标日收盘 + 收益（未来K线不足则该周期跳过）
5. REPLACE INTO bt_satisfy（先清空旧数据）
6. 满足日收盘买入，无止损（不判断回踩、不判断止损）

复用 combination_miner 的 load_klines / 因子加载逻辑，但**买入=满足日收盘，无回踩无止损**。

## 3. 后端 API（src/web/app.py）

### GET /api/bt/summary?day_level=1&days=60
返回达标组合在该周期+样本范围内的汇总，按胜率降序：
```json
{"day_level":1,"days":60,"list":[
  {"combo":"...","sample_count":100,"win_rate":68.5,"max_profit":45.2,"min_profit":-8.1,"median_profit":2.3}
]}
```
- 只统计 buy_date >= (基准日 - days 自然日) 且 profit 不为空的记录
- 基准日用最新交易日（MAX(buy_date)）
- 胜率 = SUM(profit>0)/COUNT；最大/最小/中位数盈利

### GET /api/bt/group?combo=xxx&day_level=1&days=60
返回某组合的命中明细，按 buy_date 降序：
```json
{"combo":"...","list":[
  {"dm":"...","mc":"...","buy_date":"...","start_price":...,"end_price":...,"profit":...}
]}
```

### GET /api/bt/stock?dm=xxx&combo=xxx&day_level=1
返回某股票在某组合+周期的命中记录（最近60自然日），按 buy_date 降序：
```json
{"dm":"...","combo":"...","list":[
  {"buy_date":"...","start_price":...,"end_price":...,"profit":...}
]}
```

## 4. 前端（public/index.html，「回溯分析」Tab 内重构）

三段式布局：

```
[收益周期] 单选框：1 2 3 5 7 20 60
[样本范围] 单选框：3天 7天 15天 30天 60天

[组合汇总] 表格：组合名(中文) | 样本数 | 胜率 | 最大盈利 | 最小盈利 | 中位数盈利
           （按胜率降序，点击行高亮）

[命中详情] 表格：日期 | 代码 | 名称 | 起始价 | 目标价 | 收益
           （点击上方组合后加载，点击行可进单股）

[单股详情] 表格：日期 | 起始价 | 目标价 | 收益
           （点击命中详情的股票后加载）
```

- 单选框改变 → 重新加载汇总
- 组合名用 FACTOR_CN 转中文（复用 comboCn）
- 保留手动回溯功能（原「手动回溯」区域可折叠或保留在下方）

## 验收标准

1. bt_build.py 后 bt_satisfy 有数据（达标组合 × 7周期）
2. /api/bt/summary 按 day_level+days 返回组合胜率排序
3. 前端三段式：单选框筛选 → 汇总排序 → 点击组合看命中 → 点击股票看单股
4. 组合名显示中文

## 禁止事项

- ❌ 不改因子库、组合挖掘核心逻辑（mine 保留，另写 bt_build）
- ❌ 不 git commit/push
- ❌ 不用未来数据（收益第N日只用满足日之后的数据）
- ❌ 收益第N日：同股 buy_date 之后的第 N 条交易日
