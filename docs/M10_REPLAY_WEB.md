# M10 历史回放网页 — 开发任务指令

> 供 cursor-agent 执行。核心：网页展示最优组合的历史选股记录 + K线图，供参考历史走势。

## 目标

用户想看：今天算出的高胜率组合，在历史中选出了哪些股票，并能在K线中参考它们的走势。

## 功能设计

### 1. 历史回放数据（预计算存表）

新增表 `history_replay`：
```sql
CREATE TABLE IF NOT EXISTS history_replay (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  combo VARCHAR(200) COMMENT '组合名',
  period VARCHAR(10) COMMENT '周期标签',
  dm VARCHAR(10) COMMENT '股票代码',
  mc VARCHAR(50) COMMENT '股票名称',
  buy_date DATE COMMENT '买入日',
  entry DECIMAL(10,2) COMMENT '买入价',
  stop DECIMAL(10,2) COMMENT '止损价',
  exit_price DECIMAL(10,2) COMMENT '出场价',
  ret DECIMAL(10,2) COMMENT '收益率%',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_combo (combo, period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

新增脚本 `scripts/replay_save.py`：
- 读 combo_rank 里胜率最高的组合（按训练+测试胜率降序，和 run_screen 一致）
- 遍历全市场，找出该组合的历史信号（信号日 → 回踩买入 → 持有）
- 记录每笔：dm/mc/买入日/买入价/止损价/出场价/收益率
- 写入 history_replay 表（先 DELETE 该组合旧记录再 INSERT）
- 只看测试期（近期），按买入日倒序

### 2. 后端 API（src/web/app.py 增加）

`GET /api/history` 返回：
```json
{
  "combo": "gap_up+ma_bull+shrink_pullback",
  "period": "短",
  "win_rate": 54.41,
  "expectation": 1.55,
  "records": [
    {"dm":"301206","mc":"三元生物","buy_date":"2026-08-14","entry":23.91,"stop":22.0,"exit_price":...,"ret":...,"klines":[...]}
  ]
}
```
每条 record 附带 `klines`：买入日前后各 30 天（共约60天）的 K 线，含 o/h/l/c/v/ma5/ma10/ma20，用于前端画图。

K线查询：`SELECT t,o,h,l,c,v,ma5,ma10,ma20 FROM daily_kline WHERE dm=%s AND t BETWEEN %s AND %s ORDER BY t`

### 3. 前端（public/index.html 增加）

- 顶部显示：最优组合名、周期、胜率、期望收益
- 历史记录表格：买入日 | 代码 | 名称 | 买入价 | 止损价 | 收益
- 点击某行 → 下方用 ECharts 画 K 线图（蜡烛图 + MA5/MA10/MA20 折线）
- ECharts 通过 CDN 引入：`https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js`
- K线图标注买入点和止损线

## 验收标准

1. `replay_save.py` 后 history_replay 有最优组合的历史记录
2. `/api/history` 返回组合信息 + 记录 + K线数据
3. 网页展示历史记录表格，点击能看K线图
4. K线图含蜡烛 + MA均线，标注买入点/止损线

## 禁止事项

- ❌ 不改组合挖掘、因子库、大盘过滤逻辑
- ❌ 不 git commit/push
- ❌ 历史回放只用已有数据，不调麦蕊接口（数据已在库）
