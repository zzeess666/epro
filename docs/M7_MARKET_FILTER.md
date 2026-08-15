# M7 大盘过滤 + 样本门槛 — 开发任务指令

> 供 cursor-agent 执行。核心：按板块对应指数判断大盘状态，熊市空仓，只在大盘多头时统计买入。

## 背景

诊断发现：训练期（熊市）与测试期（牛市）环境相反，导致任何组合都无法两期同时≥60%胜率。解法：大盘过滤（指数 MA20 下方时空仓）。

## 目标

1. 同步4个大盘指数的历史日K + 计算MA20
2. 组合挖掘加入「板块对应指数过滤」
3. 样本门槛 30 → 25

## 1. 指数数据（已验证接口）

```
GET /hsindex/history/{code}.SH/d/{licence}?st=YYYYMMDD&et=YYYYMMDD
```
（注意：指数接口是 `/d/`，无股票接口的 `n`）

| 指数 | 代码 | 判断板块 |
|------|------|---------|
| 上证指数 | 000001.SH | 沪市主板（600/601/603/605开头）|
| 深证成指 | 399001.SZ | 深市主板（000/001/002/003开头）|
| 科创50 | 000688.SH | 科创板（688开头）|
| 创业板指 | 399006.SZ | 创业板（300/301开头）|

## 2. 新增表与文件

```sql
CREATE TABLE IF NOT EXISTS index_kline (
  code VARCHAR(20) NOT NULL COMMENT '指数代码，如000001.SH',
  t DATE NOT NULL,
  o DECIMAL(10,2), h DECIMAL(10,2), l DECIMAL(10,2), c DECIMAL(10,2),
  v BIGINT, a DECIMAL(20,2), pc DECIMAL(10,2),
  ma20 DECIMAL(10,2),
  PRIMARY KEY (code, t)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

```
src/index/
  __init__.py
  index_sync.py        # 指数同步 + MA20计算
scripts/
  sync_index.py        # CLI：同步4个指数历史
```

`sync_index.py`：拉4个指数 2015-01-01 至今的日K，REPLACE INTO index_kline，本地算 ma20。

## 3. 大盘过滤逻辑（修改 combination_miner.py）

新增函数 `is_market_bull(dm, day)`：
1. 根据股票 dm 前缀判断所属板块，得到对应指数代码
2. 查 index_kline 该指数在 day 的收盘价 c 和 ma20
3. 若 `c > ma20` → 该板块多头，允许买入（True）
4. 否则 → 空仓（False）

**板块判定规则**（dm 前缀）：
- `688` → 科创50（000688.SH）
- `300`/`301` → 创业板指（399006.SZ）
- `600`/`601`/`603`/`605` → 上证指数（000001.SH）
- 其余（000/001/002/003）→ 深证成指（399001.SZ）

**组合挖掘时**：某股票某天命中组合，先判断 `is_market_bull(dm, day)`，为 False 则跳过该信号（视为空仓，不统计）。

## 4. 样本门槛

`win_rate_ranker.py` 的 `MIN_SAMPLE = 30` → 改为 `25`。

## 验收标准

1. `sync_index.py` 后 index_kline 有4个指数、2015年至今、含 ma20
2. 组合挖掘时，指数 MA20 下方的信号被跳过（空仓）
3. 重新跑挖掘，观察胜率是否突破60%，且样本≥25
4. 分板块过滤正确（688→科创50、300→创业板、6→上证、其余→深证）

## 禁止事项

- ❌ 不改因子库
- ❌ 不 git commit/push
- ❌ 指数接口用 `/d/`（无 `n`），别用错
- ❌ 不用未来数据（当日指数判断只用当日及之前数据）
