# EPro 需求文档（开发蓝图）

> 版本 v0.1 · 2026-08-13 · 由架构师（Hermes）整理，供 cursor-agent 开发使用

---

## 1. 项目概述

**EPro** 是一个全新设计的 A 股投研系统，定位 **稳健低风险**。与 E8（第一版，PHP，标记驱动）互补但不重复：E8 回答"这票符合什么形态"，EPro 回答"这票现在能不能买、亏了怎么办"。

### 核心功能
1. 下午收集数据（17:00 起同步全市场日K + 基本面）
2. 回溯胜率分析（策略胜率 < 60% 不上线）
3. 推荐股票（评分排序 + 理由 + 止损价）
4. 基本面查询（PE/PB/ROE/负债率等）
5. 次日实时跟踪 + 尾盘买入提醒

---

## 2. 核心原则（四铁律，硬约束）

任何推荐都必须通过以下四条，一票否决：

| # | 铁律 | 含义 |
|---|------|------|
| 1 | 先算风险再算收益 | 最大亏损 ≤ 4%（买入价到止损价距离）才进候选 |
| 2 | 回溯验证一切 | 策略回溯胜率 < 60% 不上线 |
| 3 | 宁缺毋滥 | 单日推荐 ≤ 3 只 |
| 4 | 必带止损 | 不带止损价不推荐 |

---

## 3. 技术栈

| 层 | 方案 |
|----|------|
| 语言 | Python 3.11 |
| 数据库 | MySQL 5.7（库 `epro`，账号 `epro`）|
| Web API | FastAPI |
| 前端 | 轻量静态页 + ECharts（先做简单版）|
| 调度 | cron + Python 脚本 |
| 数据源 | 麦蕊 API（2 个 Token 轮询）|

**部署**：腾讯云服务器（170.106.190.142），项目目录 `/www/wwwroot/epro/`。

---

## 4. 数据源：麦蕊 API 接口清单（已验证）

### 4.1 代码格式约定
- 数据库 `dm` 字段**存纯数字**（如 `003023`）
- 交易所单独存 `jys` 字段（`SZ`/`SH`/`BJ`）
- 调 API 时按接口要求拼接：`hsrl/ssjy` 用纯数字，`hsstock/history` 用 `003023.SZ` 后缀

### 4.2 已验证接口

| 用途 | 接口 | 返回字段 |
|------|------|---------|
| 股票列表 | `GET /hslt/list/{licence}` | `dm`(带后缀), `mc`(名称), `jys`(SZ/SH) |
| 实时行情 | `GET /hsrl/ssjy/{纯数字}/{licence}` | `p`(最新价), `pc`(涨跌幅%), `yc`(昨收), `h`(高), `l`(低), `o`(开), `v`(成交量万手), `cje`(成交额), `hs`(换手率), `lb`(量比), `pe`, `pb`(sjl), `lt`(流通市值), `sz`(总市值) |
| 历史日K | `GET /hsstock/history/{code}.SZ/d/n/{licence}?st=YYYYMMDD&et=YYYYMMDD&lt=N` | `t`(日期), `o`(开), `h`(高), `l`(低), `c`(收), `v`(量), `a`(额), `pc`(昨收) |
| 每股指标(财务) | `GET /hsstock/financial/pershareindex/{纯数字}/{licence}` | `jzrq`(截止日), `jbmgsy`(基本EPS), `xsmlv`(毛利率), `jlv`(净利率), `jqjzcsyl`(加权ROE) |
| 公司简介 | `GET /hscp/gsjj/{纯数字}/{licence}` | `name`, `market`, `ldate`, `principal` |

### 4.3 待补充接口（后续迭代）
- 主力资金流：MVP 阶段用「量比+换手率+成交额」代理，后续找专门资金流接口
- 财务报表三大表：`/hsstock/financial/balance|income|cashflow/{code}/{licence}`

---

## 5. 数据库设计（库 epro，字符集 utf8mb4）

### 表1：`stock_basic` 股票基础信息
| 字段 | 类型 | 说明 |
|------|------|------|
| dm | VARCHAR(10) PK | 纯数字代码，如 003023 |
| mc | VARCHAR(50) | 股票名称 |
| jys | VARCHAR(5) | 交易所 SZ/SH/BJ |
| ltsz | DECIMAL(20,2) | 流通市值（元）|
| zsz | DECIMAL(20,2) | 总市值（元）|
| pe | DECIMAL(10,2) | 市盈率 |
| pb | DECIMAL(10,2) | 市净率 |
| updated_at | DATETIME | 更新时间 |

### 表2：`daily_kline` 日K线
| 字段 | 类型 | 说明 |
|------|------|------|
| dm | VARCHAR(10) | 股票代码 |
| t | DATE | 交易日 |
| o/h/l/c | DECIMAL(10,2) | 开/高/低/收 |
| v | BIGINT | 成交量（手）|
| a | DECIMAL(20,2) | 成交额（元）|
| pc | DECIMAL(10,2) | 昨收 |
| ma5/ma10/ma20/ma60 | DECIMAL(10,2) | 本地计算均线 |
| PRIMARY KEY (dm, t) | | |

### 表3：`strategy_signal` 策略信号
| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT AUTO PK | |
| dm | VARCHAR(10) | |
| t | DATE | 信号日期 |
| strategy | VARCHAR(10) | A/B/C |
| score | DECIMAL(10,2) | 评分 |
| entry_price | DECIMAL(10,2) | 建议买入价 |
| stop_loss | DECIMAL(10,2) | 止损价 |
| detail | JSON | 信号详情 |
| created_at | DATETIME | |

### 表4：`recommend_result` 每日推荐
| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT AUTO PK | |
| t | DATE | 推荐日期 |
| dm | VARCHAR(10) | |
| strategy | VARCHAR(10) | 命中策略 |
| score | DECIMAL(10,2) | 综合评分 |
| reason | TEXT | 推荐理由 |
| entry_price | DECIMAL(10,2) | 建议买入价 |
| stop_loss | DECIMAL(10,2) | 止损价 |
| position_pct | DECIMAL(5,2) | 建议仓位 |
| created_at | DATETIME | |

### 表5：`backtest_result` 回溯结果
| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT AUTO PK | |
| strategy | VARCHAR(10) | |
| start_date / end_date | DATE | 回溯区间 |
| sample_count | INT | 样本数 |
| win_count | INT | 盈利次数 |
| win_rate | DECIMAL(5,2) | 胜率% |
| avg_return | DECIMAL(10,2) | 平均收益% |
| avg_loss | DECIMAL(10,2) | 平均亏损% |
| created_at | DATETIME | |

### 表6：`track_watch` 次日跟踪
| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT AUTO PK | |
| dm | VARCHAR(10) | |
| track_date | DATE | 跟踪日期 |
| status | VARCHAR(20) | 观察中/达标/不达标 |
| entry_price | DECIMAL(10,2) | 建议买入价 |
| stop_loss | DECIMAL(10,2) | 止损价 |
| current_price | DECIMAL(10,2) | 最新价 |
| updated_at | DATETIME | |

---

## 6. 三个策略算法

### 6.1 策略A：二次突破
参考 E8 的 `FalgbreakCalculator`，逻辑：
1. 首次突破：某日收盘价创近 30 日新高（突破强度 > 30 天）
2. 缩量回调：随后 1-5 天内缩量回调，**不破首次突破日低点**，收盘价 ≥ 0.95×突破日收盘
3. 再次突破：今日收盘价突破首次突破日高点，且放量

**止损**：首次突破日低点（跌破即失败）

### 6.2 策略B：缩量回踩
逻辑：
1. 趋势向上：MA5 > MA10 > MA20 多头排列
2. 缩量回踩：股价回踩 MA10 或 MA20，成交量缩至前期均量的 60% 以下
3. 止跌企稳：回踩日收出下影线或小阳线，未有效跌破均线

**止损**：跌破 MA20 且 3 日不收回

### 6.3 策略C：综合评分（多因子）
对全市场股票四维打分（各 25%）：

| 维度 | 权重 | 判断逻辑 |
|------|------|---------|
| 估值 | 25% | PE/PB 越低分越高（PE<30 满分，>50 零分）|
| 技术形态 | 25% | 均线多头、放量、创新高等 |
| 历史利润 | 25% | ROE>15% 满分、EPS 增长 |
| 资金流入 | 25% | 量比>1.5、换手率适中、成交额放大（代理指标）|

---

## 7. 评分与风控

### 7.1 统一评分
三策略候选汇合后，按 C 策略的四维评分统一打分，取综合得分排序。

### 7.2 风控过滤（一票否决）
- 最大亏损 > 4%（`entry_price` 到 `stop_loss` 距离）
- 流通市值 < 20 亿或 > 500 亿
- PE > 50 或 PB > 5
- 名称含 ST / *ST / 退市风险
- 回溯胜率 < 60% 的策略，其信号不进入推荐

### 7.3 输出规则
- 单日最多 3 只，按综合评分降序
- 每只输出：评分、命中策略、推荐理由、建议买入价、止损价、建议仓位

---

## 8. 每日流程时序

```
17:00  sync_stock_list    同步股票列表 → stock_basic
17:10  sync_daily_kline   同步全市场日K（分片并行）→ daily_kline
17:40  calc_indicator     计算 MA5/10/20/60 → daily_kline
18:00  run_strategy       跑 A/B/C 三策略 → strategy_signal
18:30  run_backtest       回溯验证各策略胜率 → backtest_result
19:00  score_rank         统一评分 + 风控过滤 → recommend_result
19:30  output_top3        输出当日 TOP3 推荐
──────────── 次日 ────────────
09:30  start_track        启动跟踪清单 → track_watch
09:30-14:30  盘中每10分钟检查候选股
14:30  tail_check         尾盘最终确认
14:30-15:00 触发提醒（满足条件 → 通知买入）
```

---

## 9. Web 页面（分阶段）

| 阶段 | 页面 | 内容 |
|------|------|------|
| P1 | 推荐页 | 今日 TOP3 + 评分 + 理由 + 止损价 + 仓位 |
| P2 | 跟踪页 | 次日候选股实时跟踪状态 |
| P3 | 回溯页 | 各策略胜率统计 + 图表 |
| P4 | 基本面页 | 个股 PE/PB/ROE/财务查询 |

MVP 先做 P1（推荐页），其余迭代补充。

---

## 10. 分阶段验收标准

| 里程碑 | 交付物 | 验收标准 |
|--------|--------|---------|
| M1 数据层 | 同步 + 计算脚本 | 全市场日K入库，MA 计算正确，无重复 |
| M2 策略层 | 三策略 + 回溯 | 每策略能输出信号，回溯胜率可计算 |
| M3 评分风控 | 统一评分 + 推荐 | 每日输出 ≤3 只，带止损价，风控生效 |
| M4 跟踪部署 | 跟踪 + cron + Web | 次日能跟踪，尾盘能提醒，Web 可见 |

---

## 11. 开发约定

1. 所有脚本放 `scripts/`，业务逻辑放 `src/`
2. 配置文件 `.env`（含密码），**不提交 git**，用 `.env.example` 占位
3. 数据库连接用 `127.0.0.1:3306`，账号 `epro`
4. 麦蕊 Token 轮询：2 个 Token 各 500 次/天，需实现 `ApiKeyRotator`
5. 所有 HTTP 请求加 10 秒超时 + 3 次重试
6. 分片同步：全市场按 `MOD(序号, 分片数)` 并行
7. 代码提交到 `main` 分支，不建功能分支

### 11.1 开发纪律（用户硬性要求）

1. **分阶段开发**：严格按 M1→M2→M3→M4 推进，每阶段独立开发、独立验收，验收通过才进入下一阶段，禁止跨阶段一次性做完（避免项目失控）
2. **适时提交 git**：每完成一个可运行的小功能就提交一次，全部提交到 `main` 分支
3. **测试数据量 ≤ 100 只股票**：开发测试阶段，同步/计算/回溯的股票数量不得超过 100 只（麦蕊 API 每 Token 每天 500 次，全市场 5000 只会耗尽额度）。上线前才考虑全量
4. **合理使用 md 文件**：需求、设计、测试报告、验收记录均用 markdown 文档记录在 `docs/` 下，保持可追溯
