"""诊断：计算组合的期望收益和盈亏比（A方案基础）"""
import sys
sys.path.insert(0, "/www/wwwroot/epro")
from src.combo.combination_miner import mine

rows = mine(limit=None)

# 期望收益 = 胜率×均盈 - (1-胜率)×|均亏|
# 但 mine() 返回的 ComboPeriodStats 没有均盈均亏，需要重算
# 这里先看样本≥25的组合分布

print("=== 样本≥25的组合（训练+测试都≥25）按测试胜率排序 ===")
valid = [r for r in rows if r.train_n >= 25 and r.test_n >= 25]
valid.sort(key=lambda r: -r.test_win_rate)
for i, r in enumerate(valid[:15], 1):
    print(f"#{i} {r.combo} {r.period}({r.hold_days}日) 训练{r.train_win_rate:.1f}%(n={r.train_n}) 测试{r.test_win_rate:.1f}%(n={r.test_n})")

print()
print(f"样本≥25的组合总数: {len(valid)}")
print(f"其中测试胜率≥50%的: {sum(1 for r in valid if r.test_win_rate >= 50)}")
print(f"其中测试胜率≥55%的: {sum(1 for r in valid if r.test_win_rate >= 55)}")
print(f"其中测试胜率≥60%的: {sum(1 for r in valid if r.test_win_rate >= 60)}")
