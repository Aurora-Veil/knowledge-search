"""兼容入口：`python ingest.py [...]` ≡ `python -m app.sync load --reset [...]`。

历史上本文件是"清空重灌"脚本（drop 三个集合 + 按 reasoning/*.json 重灌，`--yes` 才执行）。
实现已经搬进 `app/sync/load.py`，本文件只做参数映射，所以老习惯照旧可用：

    python ingest.py --dry-run   # 看会清空/写入什么（不动数据）
    python ingest.py --yes       # 真正执行：重灌 Mongo + 重建重灌 ES
    python ingest.py             # 不带确认 → 拒绝执行

想用新的增量方式（不重建 ObjectId、只推变动）：`python -m app.sync load`（默认不删）。
"""
import sys

from app.sync.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["load", "--reset", *sys.argv[1:]]))
