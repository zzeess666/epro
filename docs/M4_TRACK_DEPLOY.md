# M4 跟踪部署 — 开发任务指令

> 供 cursor-agent 执行的开发任务。严格按此文档实现。

## 目标

完成最后一层：次日盘中跟踪 + 尾盘提醒 + Web 推荐页 + cron 定时任务，让系统跑通完整闭环。

## 前置条件

- M1/M2/M3 已完成，recommend_result 有推荐数据
- 复用 config、src/db、src/api

## 新增数据库表（追加 sql/schema.sql）

```sql
CREATE TABLE IF NOT EXISTS track_watch (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  dm VARCHAR(10) NOT NULL,
  track_date DATE NOT NULL COMMENT '跟踪日期',
  status VARCHAR(20) DEFAULT '观察中' COMMENT '观察中/达标/不达标',
  entry_price DECIMAL(10,2) COMMENT '建议买入价',
  stop_loss DECIMAL(10,2) COMMENT '止损价',
  current_price DECIMAL(10,2) COMMENT '最新价',
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_date (track_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

## 新增文件

```
src/track/
  __init__.py
  track_service.py      # 跟踪清单生成 + 盘中检查
src/web/
  __init__.py
  app.py                # FastAPI Web 应用
scripts/
  run_track.py          # CLI：生成/更新跟踪 + 尾盘判断
public/
  index.html            # 推荐页（简单静态页，读 API）
crontab/
  crontab               # 定时任务示例
```

## 1. 跟踪服务（track_service.py）

### 生成跟踪清单
- 读取 recommend_result 最新推荐（前一日推荐）
- 写入 track_watch（track_date=次日，status=观察中）

### 盘中检查（run_track.py）
- 遍历 track_watch 当日观察中的股票
- 调麦蕊 `/hsrl/ssjy/{dm}/{licence}` 获取最新价
- 更新 current_price
- 判断：
  - 最新价 ≤ stop_loss → status=不达标（跌破止损）
  - 最新价在 [stop_loss, entry_price] 区间 → status=观察中
  - 14:30 后最新价 ≥ entry_price 且放量 → status=达标（尾盘可买）

### 尾盘提醒
- 14:30-15:00 运行时，输出「达标」股票的提醒文本：
  - 代码、名称、最新价、建议买入价、止损价
- 输出到 stdout（供 cron 投递），也写 Web 可查

## 2. Web 应用（app.py，FastAPI）

- `GET /api/recommend` → 返回最新推荐列表（JSON）
- `GET /api/track` → 返回当日跟踪状态（JSON）
- `GET /` → 返回 public/index.html

前端 index.html 极简：展示今日推荐（代码/策略/评分/买入价/止损价）+ 跟踪状态表格。可用原生 JS + fetch，无需框架。

## 3. cron 定时任务（crontab/crontab 示例）

```
# 数据同步 + 策略 + 推荐（交易日 17:00 后）
0 17 * * 1-5  cd /www/wwwroot/epro && .venv/bin/python scripts/sync_daily_kline.py && .venv/bin/python scripts/calc_indicator.py && .venv/bin/python scripts/run_strategy.py && .venv/bin/python scripts/run_backtest.py && .venv/bin/python scripts/run_recommend.py

# 次日盘中跟踪（每10分钟，仅交易日盘中）
*/10 9-15 * * 1-5  cd /www/wwwroot/epro && .venv/bin/python scripts/run_track.py
```

（cron 示例写入文件即可，实际安装由架构师操作）

## 验收标准（M4 完成必须满足）

1. `python scripts/run_track.py` 能生成跟踪清单、更新价格、判断达标
2. `python src/web/app.py` 或 `uvicorn` 能启动，`/api/recommend` 返回推荐 JSON
3. 尾盘时段运行能输出「达标」提醒文本
4. crontab 示例文件存在且命令正确
5. 全流程：同步→策略→回溯→推荐→跟踪 串起来可跑

## 禁止事项

- ❌ 禁止全量同步（≤100 只）
- ❌ 禁止 git commit/push（架构师验收后统一提交）
- ❌ 禁止引入复杂前端框架（原生 JS 即可）
- ❌ 跟踪检查仅针对 track_watch 里的股票（≤3只），禁止全市场扫
