"""Mongo(knowledge_db) → ES(knowledge_*) 同步工具层。

模块职责：admin（索引生命周期）/ full（全量灌）/ one（写后单条同步）/ reconcile（对账）。
命令入口见 `cli.py`：`python -m app.sync <子命令>` 与顶层 `python full_sync.py <子命令>` 等价。
"""
