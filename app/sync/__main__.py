"""`python -m app.sync` 入口（等价 `python full_sync.py`）。"""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
