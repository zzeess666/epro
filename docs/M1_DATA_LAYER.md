# M1 数据层 — 开发任务指令

> 供 cursor-agent 执行的开发任务。请严格按此文档实现，不要偏离范围。

## 目标

实现数据层：同步股票列表 + 日K线 + 本地计算 MA 均线，入库 MySQL。

## 前置条件

- Python 3.11 可用
- MySQL 库 `epro` 已建，账号 `epro` / 密码见 `.env`
- 麦蕊 API 2 个 Token（见 `.env`，各 500 次/天）
- **测试范围：仅前 100 只股票**（按代码排序），严禁全量同步

## 依赖（requirements.txt）

```
pymysql
requests
python-dotenv
```

## 文件结构（在 /www/wwwroot/epro 下）

```
.env.example          # 环境变量示例（不含真实密码）
requirements.txt      # 依赖
sql/schema.sql        # 建表 SQL
config/config.py      # 读取 .env 配置（数据库、麦蕊 token 列表）
src/api/api_key_rotator.py   # Token 轮询器
src/api/mairui_client.py     # 麦蕊 API 客户端
src/db/connection.py         # 数据库连接（pymysql）
src/sync/stock_list_sync.py  # 股票列表同步
src/sync/daily_kline_sync.py # 日K同步
src/sync/indicator_calc.py   # MA 计算
scripts/sync_stock_list.py   # CLI 入口：同步股票列表
scripts/sync_daily_kline.py  # CLI 入口：同步日K
scripts/calc_indicator.py    # CLI 入口：计算 MA
```

## 数据库表（sql/schema.sql，库 epro）

```sql
CREATE TABLE IF NOT EXISTS stock_basic (
  dm VARCHAR(10) PRIMARY KEY COMMENT '纯数字代码',
  mc VARCHAR(50) COMMENT '名称',
  jys VARCHAR(5) COMMENT '交易所 SZ/SH/BJ',
  ltsz DECIMAL(20,2) COMMENT '流通市值',
  zsz DECIMAL(20,2) COMMENT '总市值',
  pe DECIMAL(10,2) COMMENT '市盈率',
  pb DECIMAL(10,2) COMMENT '市净率',
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS daily_kline (
  dm VARCHAR(10) NOT NULL COMMENT '纯数字代码',
  t DATE NOT NULL COMMENT '交易日',
  o DECIMAL(10,2), h DECIMAL(10,2), l DECIMAL(10,2), c DECIMAL(10,2),
  v BIGINT COMMENT '成交量(手)',
  a DECIMAL(20,2) COMMENT '成交额(元)',
  pc DECIMAL(10,2) COMMENT '昨收',
  ma5 DECIMAL(10,2), ma10 DECIMAL(10,2), ma20 DECIMAL(10,2), ma60 DECIMAL(10,2),
  PRIMARY KEY (dm, t)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

## 麦蕊 API（已验证格式）

| 用途 | 接口 |
|------|------|
| 股票列表 | `GET /hslt/list/{licence}` 返回 `[{dm:"000001.SZ", mc:"平安银行", jys:"SZ"},...]` |
| 历史日K | `GET /hsstock/history/{code}.SZ/d/n/{licence}?st=YYYYMMDD&et=YYYYMMDD&lt=N` 返回 `[{t,o,h,l,c,v,a,pc},...]` |

**代码格式**：`dm` 存纯数字；调日K接口时拼 `{dm}.{jys}`（如 `003023.SZ`）。

## 各模块要点

### api_key_rotator.py
- 维护 token 列表（从 .env 读取，逗号分隔）
- `next()` 方法轮询返回下一个 token
- 记录每日每个 token 的调用次数，超 500 次跳过（防超限）

### mairui_client.py
- 封装 HTTP GET，10 秒超时，失败重试 3 次
- `get_stock_list()` → 返回股票列表
- `get_daily_kline(code, jys, start, end, limit)` → 返回日K数据
- 内部用 ApiKeyRotator 取 token

### stock_list_sync.py
- 调 get_stock_list()
- 解析 dm 为纯数字（去掉 .SZ/.SH 后缀），存 dm + jys
- **仅取前 100 只**（按 dm 排序）入库
- 用 REPLACE INTO 防重复

### daily_kline_sync.py
- 遍历 stock_basic 的股票（≤100 只）
- 每只调 get_daily_kline，同步近 120 个交易日的日K
- REPLACE INTO daily_kline 入库
- 进度日志：每 10 只打印一次进度

### indicator_calc.py
- 读 daily_kline，按 dm 分组，日期升序
- 用 pandas 或纯 Python 计算 ma5/ma10/ma20/ma60
- UPDATE 回写 daily_kline
- 注意：MA 计算不调麦蕊接口，纯本地计算

### config.py
- 用 python-dotenv 读 .env
- 暴露：DB_*、MAIRUI_API_KEYS（list）、SYNC_STOCK_LIMIT（默认100）

## 验收标准（M1 完成后必须满足）

1. `php -l` 不适用（Python），改为 `python -m py_compile` 各文件无语法错误
2. `python scripts/sync_stock_list.py` 后，stock_basic 有 100 条记录
3. `python scripts/sync_daily_kline.py` 后，daily_kline 有数据，且股票数 ≤ 100
4. `python scripts/calc_indicator.py` 后，daily_kline 的 ma5/ma10/ma20/ma60 非空
5. 重复运行同步脚本不产生重复数据（REPLACE INTO 生效）
6. Token 轮询生效，单个 token 调用不超过 500 次/天

## 禁止事项

- ❌ 禁止全量同步（>100 只）
- ❌ 禁止把 .env 提交到 git
- ❌ 禁止调用麦蕊的 MA/MACD 接口（必须本地计算）
- ❌ 禁止跨 M1 范围实现策略/评分/Web 功能
