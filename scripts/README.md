# scripts/ —— 探索、诊断与验证脚本（非测试）

这些是开发过程中的辅助脚本，不属于 pytest 测试套件，按用途分目录：

- `probe/`   —— 接口探测脚本（竞彩官网、understat、football-data 等），多为一次性探索
- `diag/`    —— 诊断脚本（Dixon-Coles 收敛/梯度分析等）
- `validate/` —— 验证脚本（`validate_shrinkage.py` 对比收缩先验、`validate_ml.py` 对比 DC/Elo/ML）

运行方式（从项目根目录）：

```powershell
python scripts\validate\validate_shrinkage.py
python scripts\validate\validate_ml.py
python scripts\diag\diag_dc.py
```

正式测试在 `tests/`，用 `python tests\test_X.py` 运行。
