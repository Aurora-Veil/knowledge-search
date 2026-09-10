"""索引生命周期：存在判断 / 按 mapping/*.json 建索引 / drop / recreate / mapping 差异提示。

约定：默认路径绝不 drop 已有索引；drop 只发生在显式 `--recreate`。
"""
