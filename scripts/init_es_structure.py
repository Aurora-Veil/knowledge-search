# scripts/init_es_structure.py —— 按 mapping/ 建索引，不灌数据。

import argparse
import json
import sys
from pathlib import Path

# repo root on sys.path, so this runs from any working directory
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from elasticsearch import Elasticsearch

from app.config import es_auth, es_hosts

MAPPING_DIR = ROOT / "mapping"

# 结构清单：索引名 -> mapping 文件。
# 检索代码写死在这些字段名和 dense_vector 的维度上，改这里要连检索一起看。
INDICES = {
    "knowledge_source":       "source_mapping.json",
    "knowledge_evidence":     "evidence_mapping.json",
    "knowledge_viewpoint":    "viewpoint_mapping.json",
    "knowledge_report_index": "report_mapping.json",
}


def client() -> Elasticsearch:
    return Elasticsearch(es_hosts(), basic_auth=es_auth())


def load_mapping(index: str) -> dict:
    return json.loads((MAPPING_DIR / INDICES[index]).read_text(encoding="utf-8"))


def create(es: Elasticsearch, index: str, *, recreate: bool = False) -> None:
    if es.indices.exists(index=index):
        if not recreate:
            print(f"  {index} 已存在，不动")
            return
        es.indices.delete(index=index)
        print(f"  {index} 已删除")
    body = load_mapping(index)
    es.indices.create(index=index, settings=body.get("settings"),
                      mappings=body.get("mappings"))
    print(f"  {index} 已创建")


def require(es: Elasticsearch, index: str) -> None:
    """灌数脚本用它确认结构已经就位。"""
    if not es.indices.exists(index=index):
        raise SystemExit(
            f"{index} 不存在。建索引与灌数据是分开的，先建结构：\n"
            f"  python scripts/init_es_structure.py {index}"
        )


def main() -> None:
    ap = argparse.ArgumentParser(description="按 mapping/ 建索引，建完就可以灌数据")
    ap.add_argument("index", nargs="*", help="要处理的索引，默认全部")
    ap.add_argument("--recreate", action="store_true",
                    help="先删后建，该索引的数据会丢。必须点名索引")
    ap.add_argument("--list", action="store_true", help="只打印结构清单")
    args = ap.parse_args()

    if args.list:
        for index, mapping in INDICES.items():
            print(f"  {index:<26} {mapping}")
        return

    unknown = [i for i in args.index if i not in INDICES]
    if unknown:
        raise SystemExit(f"不在结构清单里：{', '.join(unknown)}；用 --list 看清单")
    if args.recreate and not args.index:
        raise SystemExit("--recreate 必须点名索引，避免一次删光")

    targets = args.index or list(INDICES)
    if args.recreate:
        print("== 先删后建，以下索引的数据会丢 ==")
    else:
        print("== 缺什么建什么，已有的不动 ==")

    es = client()
    try:
        for index in targets:
            create(es, index, recreate=args.recreate)
    finally:
        es.close()
    print(f"\nOK: {len(targets)} 个索引就位")


if __name__ == "__main__":
    main()
