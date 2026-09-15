from __future__ import annotations

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "knowledge_db"

ES_URL = "http://localhost:9200"

# Vector search. 
ENABLE_VECTOR_SEARCH = True

# Fusing BM25 and kNN means two ES requests per index, so ``type=all`` costs six.
# ES Retriever API RRF disable for Basic :(
ES_SEARCH_WORKERS = 12

OBJECT_TYPES: tuple[str, ...] = ("source", "evidence", "viewpoint")

INDEX_BY_TYPE: dict[str, str] = {
    "source": "knowledge_source",
    "evidence": "knowledge_evidence",
    "viewpoint": "knowledge_viewpoint",
}

# object_type → Mongo collection
COLLECTION_BY_TYPE: dict[str, str] = {
    "source": "sources",
    "evidence": "evidence",
    "viewpoint": "viewpoints",
}
