"""全量灌：Mongo 三集合 → ES 三索引（分块 bulk，解析真实成功/失败计数）。

约定：计数取 bulk 返回值而非 count_documents；失败时退出码非 0。
"""
