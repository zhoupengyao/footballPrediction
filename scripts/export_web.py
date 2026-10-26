"""站点数据导出入口：python scripts/export_web.py"""
from __future__ import annotations

import sys
from pathlib import Path

# 允许直接以脚本方式运行（不依赖 pip install -e .）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.web_export import main  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())
