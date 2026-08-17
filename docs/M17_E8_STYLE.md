# M17 全页面 e8 风格重构 — 开发任务指令

> 供 cursor-agent 执行。把 EPro 的 HTML 页面完全按 e8 的视觉风格重构，信息更紧凑。

## 目标

把 EPro 的 `public/index.html` 和样式完全按 e8 的设计系统重写：
- CSS 设计系统（变量 + 基础样式）
- Card 卡片布局（圆角 + 阴影）
- Chip 标签式选择器（替代单选框）
- 信息紧凑排列（减少留白）
- 保持所有 JS 逻辑不变

## 1. 创建 public/assets/css/app.css

把以下 e8 的 CSS 设计系统写入 `public/assets/css/app.css`（748行，完整复制，不需要改）：

```css
:root {
  --bg: #f2f3f5;
  --card: #fff;
  --primary: #1e9fff;
  --text: #222;
  --muted: #888;
  --border: #e8e8e8;
  --safe-bottom: env(safe-area-inset-bottom, 0px);
}
* { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
html, body { margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif; background: var(--bg); color: var(--text); font-size: 15px; line-height: 1.5; }
.hidden { display: none !important; }
#app { min-height: 100vh; padding-bottom: calc(56px + var(--safe-bottom)); }
.header { position: sticky; top: 0; z-index: 10; background: var(--primary); color: #fff; padding: 12px 16px; font-size: 17px; font-weight: 600; }
.panel { padding: 12px; }
.card { background: var(--card); border-radius: 10px; padding: 14px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
.card h3 { margin: 0 0 8px; font-size: 15px; }
.muted { color: var(--muted); font-size: 13px; }
.stat-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.stat-item { background: #f8fafc; border-radius: 8px; padding: 10px; text-align: center; }
.stat-item strong { display: block; font-size: 20px; color: var(--primary); }
.filters { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { border: 1px solid var(--border); background: #fff; border-radius: 16px; padding: 6px 12px; font-size: 13px; cursor: pointer; user-select: none; }
.chip.active { background: var(--primary); border-color: var(--primary); color: #fff; }
.btn { display: inline-block; width: 100%; border: 0; border-radius: 8px; background: var(--primary); color: #fff; padding: 12px; font-size: 16px; cursor: pointer; }
.stock-item { border-bottom: 1px solid var(--border); padding: 12px 0; }
.stock-item:last-child { border-bottom: 0; }
.stock-title { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.stock-title a { color: var(--primary); text-decoration: none; font-weight: 600; }
.pct-up { color: #e54545; }
.pct-down { color: #1aab5a; }
.stock-index { color: var(--muted); font-size: 13px; font-weight: normal; }
.stock-title-main { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; min-width: 0; }
.stock-sub { margin-top: 4px; font-size: 12px; }
.stock-meta { margin-top: 2px; font-size: 12px; }
.stock-actions { margin: 8px 0 4px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.follow-btn { border: 1px solid var(--primary); background: #fff; color: var(--primary); border-radius: 14px; padding: 4px 12px; font-size: 12px; cursor: pointer; }
.follow-btn.followed { background: #fff5f5; border-color: #e54545; color: #e54545; }
.follow-meta { font-size: 12px; color: var(--muted); }
.follow-item { border-bottom: 1px solid var(--border); padding: 12px 0; }
.follow-item:last-child { border-bottom: 0; }
.follow-item-head { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.follow-code { flex: 1; min-width: 0; color: var(--primary); text-decoration: none; font-weight: 600; }
.follow-fields { margin-top: 8px; display: grid; grid-template-columns: 1fr 1fr; gap: 6px 12px; font-size: 13px; }
.follow-fields > div:last-child { grid-column: 1 / -1; }
.follow-label { color: var(--muted); margin-right: 6px; }
.tabbar { position: fixed; left: 0; right: 0; bottom: 0; display: flex; background: #fff; border-top: 1px solid var(--border); padding-bottom: var(--safe-bottom); z-index: 20; }
.tabbar button { flex: 1; border: 0; background: transparent; padding: 8px 0; font-size: 11px; color: var(--muted); }
.tabbar button.active { color: var(--primary); font-weight: 600; }
.chart-tab-body { background: #fafafa; border-radius: 8px; overflow: hidden; min-height: 120px; }
.chart-img { display: block; width: 100%; max-width: 100%; height: auto; vertical-align: top; min-height: 100px; background: #f0f0f0; }
.recommend-group-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
.recommend-group-head h3 { margin: 0; font-size: 16px; }
.recommend-history { margin-top: 10px; padding-top: 10px; border-top: 1px dashed var(--border); }
.recommend-history-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.recommend-history-table th, .recommend-history-table td { padding: 4px 6px; border-bottom: 1px solid var(--border); text-align: left; }
.up { color: #e54545; font-weight: 600; }
.down { color: #1aab5a; font-weight: 600; }
```

## 2. 重写 public/index.html

### 结构要求

```
<head>
  <link rel="stylesheet" href="/assets/css/app.css">
</head>
<body>
  <div id="app">
    <div class="header">EPro 投研</div>
    
    <!-- 今日推荐 Tab -->
    <div id="tab-recommend" class="tab-pane">
      <div class="panel">
        <div class="card">
          <div class="meta" id="rec-date"></div>
          <div id="recommend-list"></div>
        </div>
        <div class="card" id="track-card">
          <div class="meta" id="track-date"></div>
          <div id="track-list"></div>
        </div>
      </div>
    </div>
    
    <!-- 当日信号 Tab -->
    <div id="tab-signal" class="tab-pane">
      <div class="panel">
        <div class="card">
          <div class="meta" id="signal-meta">从回溯分析点击组合名查看</div>
          <div id="signal-list"><div class="muted">从回溯分析点击组合名查看当日信号</div></div>
        </div>
      </div>
    </div>
    
    <!-- 历史回放 Tab -->
    <div id="tab-history" class="tab-pane">
      <div class="panel">
        <div class="card">
          <div class="meta" id="history-meta">加载中…</div>
          <div id="history-list"></div>
        </div>
        <div class="card" id="kline-card" style="display:none">
          <div class="meta" id="chart-title"></div>
          <div id="kline-chart" style="width:100%;height:320px"></div>
        </div>
      </div>
    </div>
    
    <!-- 回溯分析 Tab -->
    <div id="tab-analyze" class="tab-pane">
      <div class="panel">
        <div class="card">
          <div class="filters" id="bt-level-filters"><!-- Chip选择器 --></div>
          <div class="filters" id="bt-days-filters" style="margin-top:8px"><!-- Chip选择器 --></div>
        </div>
        <div class="card">
          <div class="meta" id="bt-summary-meta">加载中…</div>
          <div id="bt-summary-list"></div>
        </div>
        <div class="card">
          <div class="meta" id="bt-group-meta">点击上方组合查看详情</div>
          <div id="bt-group-list"></div>
        </div>
        <div class="card">
          <div class="meta" id="bt-stock-meta">点击命中详情中的股票查看</div>
          <img id="bt-stock-kline" class="chart-img" alt="日K" onerror="this.style.display='none'">
          <div id="bt-stock-list" style="margin-top:8px"></div>
        </div>
      </div>
    </div>
    
    <div class="tabbar" id="tab-bar"><!-- 4个按钮 --></div>
  </div>
</body>
```

### JS 逻辑不变

保留所有现有 JavaScript 逻辑（`FACTOR_CN`、`comboCn`、`sinaDailyImg`、`fetch` 调用、`renderKline`、`switchTab` 等），只改变渲染 HTML 的方式（从 table 改为 card/list 形式）。

### Chip 选择器（替代单选框）

e8 用 `.chip` 标签作为选择器，替代 `<input type="radio">`。点击 chip 切换 active class，调用 `loadBtSummary()`。

### 关键渲染规则

- **今日推荐**：每个股票一个 `.stock-item`，显示代码/名称 + 策略 + 评分 + 买入/止损
- **历史回放**：每个记录一个 `.follow-item`，显示买入日/代码/名称/买入价/止损/收益，`.follow-item` 可点击加载K线
- **回溯分析组合汇总**：每个组合一个 `.follow-item`，显示组合名（中文）+ 样本数 + 胜率 + 最大/最小/中位数盈利，**组合名可点击跳当日信号**（class="follow-code combo-link"）
- **命中详情**：每个命中一个 `.stock-item`，显示日期/代码/名称/起始价/目标价/收益
- **单股详情**：显示新浪日K图（`sinaDailyImg`） + 每个命中日期一个 `.stock-item`
- 收益正数用 `.up`，负数用 `.down`

## 3. 修改 app.py

添加路由：
```python
@app.get("/assets/css/app.css")
def app_css():
    return FileResponse(PUBLIC_DIR / "assets" / "css" / "app.css", media_type="text/css")
```

## 验收标准

1. 页面使用 e8 的 CSS 设计系统（变量/卡片/chip/配色）
2. 4个Tab切换正常，内容正确
3. 回溯分析 Chip 选择器切换调用 loadBtSummary()
4. 点击组合名跳转当日信号 Tab
5. 所有 API 数据正确渲染
6. K线图（ECharts）正常显示

## 禁止

- ❌ 不改后端业务逻辑（API 不变）
- ❌ 不改 JS 逻辑（只改渲染 HTML 的生成方式）
- ❌ 不 git commit/push
