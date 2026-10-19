"""把 search_log 里出现过的查询批量编码进 query_vec。"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx                                                  # noqa: E402
import psycopg                                                # noqa: E402

from app.config import pg_dsn                                 # noqa: E402
from app.search import vector_cache                           # noqa: E402

SELECT_QUERIES = """
    select query, count(*) as n
      from search_log
     where outcome = 'ok'
       and query <> ''
       and created_at > now() - make_interval(days => %s)
     group by 1
    having count(*) >= %s
     order by n desc
"""

INSERT = """
    insert into query_vec (model, dim, instruction_hash, text_hash, vec)
    values (%s, %s, %s, %s, %s)
    on conflict (model, dim, instruction_hash, text_hash) do nothing
"""


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default="", help="默认取 .env 的 PG_DSN")
    ap.add_argument("--encoder", default="http://127.0.0.1:8020")
    ap.add_argument("--days", type=int, default=30, help="搜索日志回看天数")
    ap.add_argument("--limit", type=int, default=0, help="最多灌多少条，0 为不限")
    ap.add_argument("--min-count", type=int, default=1, help="只灌出现次数 ≥ 该值的查询")
    ap.add_argument("--batch", type=int, default=32, help="每次 /encode 的条数")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--dry-run", action="store_true", help="只统计，不编码不写库")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    model, dim, instruction_hash = vector_cache.identity()
    dsn = args.dsn or pg_dsn()

    with psycopg.connect(dsn) as conn:
        sql = SELECT_QUERIES + (" limit %s" if args.limit else "")
        params: list[object] = [args.days, args.min_count]
        if args.limit:
            params.append(args.limit)
        rows = conn.execute(sql, params).fetchall()

        texts = list(dict.fromkeys(q.strip() for q, _ in rows if q.strip()))
        existing = {r[0] for r in conn.execute(
            "select text_hash from query_vec"
            " where model = %s and dim = %s and instruction_hash = %s",
            (model, dim, instruction_hash))}

        print(f"日志里 {len(rows)} 个查询（近 {args.days} 天，出现 ≥{args.min_count} 次），"
              f"去重后 {len(texts)} 条；库里已有 {len(existing)} 行")
        print(f"键材料 model={model} dim={dim} instruction_hash={instruction_hash.hex()}")

        todo = [t for t in texts if vector_cache.text_hash(t) not in existing]
        print(f"需要编码 {len(todo)} 条，跳过 {len(texts) - len(todo)} 条\n")
        if args.dry_run or not todo:
            return 0

        inserted = failed = 0
        started = time.perf_counter()
        with httpx.Client(timeout=args.timeout) as client:
            for i in range(0, len(todo), args.batch):
                chunk = todo[i:i + args.batch]
                res = client.post(f"{args.encoder}/encode",
                                  json={"texts": chunk, "kind": "query"})
                res.raise_for_status()
                vectors = res.json()["vectors"]
                if len(vectors) != len(chunk):
                    raise SystemExit(f"编码服务返回 {len(vectors)} 条，送出 {len(chunk)} 条")

                payload = []
                for text, vector in zip(chunk, vectors):
                    raw = vector_cache.pack(vector)
                    if raw is None:
                        failed += 1
                        continue
                    payload.append((model, dim, instruction_hash,
                                    vector_cache.text_hash(text), raw))
                if payload:
                    with conn.cursor() as cur:
                        cur.executemany(INSERT, payload)
                    conn.commit()
                    inserted += len(payload)

                done = min(i + args.batch, len(todo))
                if (i // args.batch) % 10 == 9 or done == len(todo):
                    elapsed = time.perf_counter() - started
                    rate = done / elapsed if elapsed else 0.0
                    eta = (len(todo) - done) / rate if rate else 0.0
                    print(f"  {done}/{len(todo)}  已写入 {inserted}  "
                          f"{rate:.0f} 条/s  余 {eta:.0f}s", flush=True)

        total = conn.execute("select count(*) from query_vec").fetchone()[0]
        print(f"\n完成：写入 {inserted} 条，失败 {failed} 条，"
              f"耗时 {time.perf_counter() - started:.1f}s；query_vec 现有 {total} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
