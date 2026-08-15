"""诊断：输出所有组合的胜率排行（不过滤60%门槛）"""
import sys
sys.path.insert(0, "/www/wwwroot/epro")
from src.combo.combination_miner import mine

rows = mine(limit=None)

def avg(r):
    return (r.train_win_rate + r.test_win_rate) / 2.0

lines = []
lines.append("=== 综合胜率 TOP 20（训练+测试平均）===")
for i, r in enumerate(sorted(rows, key=lambda r: -avg(r))[:20], 1):
    lines.append(f"#{i} {r.combo} {r.period}({r.hold_days}日) 训练{r.train_win_rate:.1f}%(n={r.train_n}) 测试{r.test_win_rate:.1f}%(n={r.test_n}) 综合{avg(r):.1f}%")

lines.append("")
lines.append("=== 按测试期胜率 TOP 10 ===")
for i, r in enumerate(sorted(rows, key=lambda r: -r.test_win_rate)[:10], 1):
    lines.append(f"#{i} {r.combo} {r.period}({r.hold_days}日) 测试{r.test_win_rate:.1f}%(n={r.test_n}) 训练{r.train_win_rate:.1f}%(n={r.train_n})")

lines.append("")
lines.append("=== 按训练期胜率 TOP 10 ===")
for i, r in enumerate(sorted(rows, key=lambda r: -r.train_win_rate)[:10], 1):
    lines.append(f"#{i} {r.combo} {r.period}({r.hold_days}日) 训练{r.train_win_rate:.1f}%(n={r.train_n}) 测试{r.test_win_rate:.1f}%(n={r.test_n})")

text = "\n".join(lines)
with open("/www/wwwroot/epro/storage/logs/combo_rank_diag.txt", "w", encoding="utf-8") as f:
    f.write(text)
print(text)
