"""写后单条同步：sync_one(project_id, oirf_id) —— 有则 upsert，Mongo 已无则从 ES 删除。

约定：ES 不可用时把异常抛给调用方，不静默；不启长连接（Change Streams 不在本层）。
"""
