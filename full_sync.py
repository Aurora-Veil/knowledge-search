"""兼容入口：`python full_sync.py <子命令>` 等价 `python -m app.sync <子命令>`。

原脚本（自建 Mongo/ES 连接、常量副本、缺 import os）已拆进 app/sync/ 包：
索引生命周期 → app/sync/admin.py，全量灌 → app/sync/full.py，
单条同步 → app/sync/one.py，对账 → app/sync/reconcile.py。
"""
from app.sync.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
