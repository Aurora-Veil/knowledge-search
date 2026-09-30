"""报告检索压测：并发打 /api/v1/reports/search，采样 PG / ES / 编码服务，最后核对落库行数。

用法（仓库根目录）：
    $env:PYTHONIOENCODING='utf-8'; $env:PYTHONPATH=(Get-Location).Path
    python stress/stress_search.py --requests 200 --concurrency 40 --mode mixed
    python stress/stress_search.py --soak 15 --concurrency 40 --json      # 耐久 15 分钟
    python stress/stress_search.py --api objects --mode paging            # 改打对象检索

mode（负载形态）：
    same    每次请求完全相同——最坏情况：同一行 search_history 上抢行锁
    paging  同一个检索，page 在 1..10 里轮转（窗口内，应全部 200）
    mixed   20 个报告主题词轮转——走插入路径
    login   N 次并发登录——Argon2 吃 CPU，抢的是线程池

报告接口额外参数：--match-mode / --time-weight / --layout / --days
结果 JSON 默认写 stress/stress-<run-id>.json（--json 打开，--out 指定路径）。

会自建账号（默认 stress1，已存在则跳过）。清理：
    DELETE FROM search_history WHERE user_id = (SELECT id FROM users WHERE username='stress1');
    DELETE FROM search_log      WHERE user_id = (SELECT id FROM users WHERE username='stress1');
    DELETE FROM users WHERE username = 'stress1';
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx                                                # noqa: E402
import psycopg                                              # noqa: E402

from app.config import ES_HOSTS, ES_PASSWORD, ES_USER, pg_dsn   # noqa: E402
from embedding.config import ENCODER_URL                    # noqa: E402

TOPICS = [
    "人工智能", "大模型", "新能源汽车", "储能", "半导体", "机器人", "医疗健康",
    "光伏", "碳中和", "数字经济", "智能制造", "生物医药", "芯片", "低空经济",
    "氢能", "锂电", "工业互联网", "元宇宙", "出海", "消费",
]

OBJECT_QUERIES = [
    "能源", "光伏", "储能", "风电", "氢能", "碳中和", "电力市场", "锂电",
    "电网", "碳排放", "天然气", "煤炭", "核电", "需求响应", "虚拟电厂",
    "碳交易", "分布式", "充电桩", "特高压", "绿证",
]

PATH_BY_API = {"reports": "/api/v1/reports/search", "objects": "/api/v1/search"}

# 应用侧连接池是 max_size=10 / connection(timeout=2.0)（app/db.py、app/history/store.py）
POOL_MAX = 10


def body_for(i: int, args) -> dict:
    if args.api == "objects":
        if args.mode == "same":
            return {"q": OBJECT_QUERIES[0], "size": 20, "page": 1}
        if args.mode == "paging":
            return {"q": OBJECT_QUERIES[0], "size": 20, "page": i % 10 + 1}
        return {"q": OBJECT_QUERIES[i % len(OBJECT_QUERIES)], "size": 20}

    body: dict = {"q": TOPICS[i % len(TOPICS)] if args.mode == "mixed" else TOPICS[0],
                  "size": 20}
    if args.mode == "paging":
        body["page"] = i % 10 + 1
    if args.match_mode != "or":
        body["mode"] = args.match_mode
    if args.time_weight:
        body["time_weight"] = args.time_weight
    if args.layout:
        body["layout"] = args.layout
    if args.days:
        body["publish_date_from"] = (date.today() - timedelta(days=args.days)).isoformat()
    return body


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))]


def latency_block(latencies: list[float]) -> dict:
    if not latencies:
        return {}
    return {"count": len(latencies),
            "p50": pct(latencies, 50), "p90": pct(latencies, 90),
            "p95": pct(latencies, 95), "p99": pct(latencies, 99),
            "max": max(latencies), "mean": statistics.fmean(latencies)}


class Sampler(threading.Thread):
    """每 interval 秒记一次：PG 后端数 / 行锁等待、ES search 线程池、编码服务队列与批大小；
    每 rss_every 秒记一次本机 python 进程的 RSS 与句柄合计（含编码服务与压测脚本自身）。"""

    PG_SQL = """
    SELECT count(*) AS backends,
           count(*) FILTER (WHERE wait_event_type = 'Lock') AS lock_waits
    FROM pg_stat_activity
    WHERE datname = current_database()
    """

    ES_CAT = "/_cat/thread_pool/search"

    RSS_PS = ("$p=Get-Process -Name python* -ErrorAction SilentlyContinue;"
              "if($p){(($p|Measure-Object WorkingSet64 -Sum).Sum/1MB);"
              "(($p|Measure-Object HandleCount -Sum).Sum);"
              "(@($p).Count)}")

    def __init__(self, interval: float = 1.0, rss_every: float = 30.0) -> None:
        super().__init__(daemon=True)
        self.interval = interval
        self.rss_every = rss_every
        self.stop_flag = threading.Event()
        self.samples: list[dict] = []
        self.rss: list[dict] = []
        self.errors: list[str] = []
        self._es_url = ES_HOSTS[0].rstrip("/") if ES_HOSTS else None
        admin_pw = os.getenv("ES_ELASTIC_PASSWORD", "")
        if admin_pw:                                 # 线程池采样要 cluster monitor，应用角色没有
            self._es_auth = ("elastic", admin_pw)
        else:
            self._es_auth = (ES_USER, ES_PASSWORD) if ES_USER and ES_PASSWORD else None
        self._enc_url = ENCODER_URL.rstrip("/") if ENCODER_URL else None

    def _pg(self, conn) -> dict:
        row = conn.execute(self.PG_SQL).fetchone()
        return {"pg_backends": row[0], "pg_lock_waits": row[1]} if row else {}

    def _es(self, client: httpx.Client) -> dict:
        if not self._es_url:
            return {}
        res = client.get(self._es_url + self.ES_CAT, auth=self._es_auth,
                         params={"format": "json", "h": "queue,rejected,active"})
        res.raise_for_status()
        rows = res.json()
        return {"es_queue": sum(int(r.get("queue", 0)) for r in rows),
                "es_rejected": sum(int(r.get("rejected", 0)) for r in rows),
                "es_active": max((int(r.get("active", 0)) for r in rows), default=0)}

    def _encoder(self, client: httpx.Client) -> dict:
        if not self._enc_url:
            return {}
        res = client.get(self._enc_url + "/metrics", timeout=1.0)
        res.raise_for_status()
        body = res.json()
        return {"enc_queue": body.get("queue"), "enc_batch": body.get("last_batch")}

    def _rss(self) -> dict:
        if os.name != "nt" or self.rss_every <= 0:
            return {}
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                                  "-Command", self.RSS_PS],
                                 capture_output=True, text=True, timeout=20).stdout
            values = [float(v) for v in out.split()]
        except Exception as exc:                            # noqa: BLE001
            note = f"RSS 采样失败：{type(exc).__name__}: {exc}"
            if note not in self.errors:
                self.errors.append(note)
            return {}
        if len(values) < 3:
            return {}
        return {"rss_mb": values[0], "handles": int(values[1]), "procs": int(values[2])}

    def run(self) -> None:
        try:
            with psycopg.connect(pg_dsn(), autocommit=True) as conn, \
                    httpx.Client(timeout=2.0) as client:
                next_rss = 0.0
                while not self.stop_flag.is_set():
                    sample = self._pg(conn)
                    for name, fn in (("es", self._es), ("encoder", self._encoder)):
                        try:
                            sample.update(fn(client))
                        except Exception as exc:            # noqa: BLE001
                            note = f"{name} 采样失败：{type(exc).__name__}: {exc}"
                            if note not in self.errors:
                                self.errors.append(note)
                    self.samples.append(sample)
                    if self.rss_every > 0 and time.monotonic() >= next_rss:
                        next_rss = time.monotonic() + self.rss_every
                        rss = self._rss()
                        if rss:
                            self.rss.append(rss)
                    self.stop_flag.wait(self.interval)
        except Exception as exc:                            # noqa: BLE001
            self.errors.append(f"采样线程退出：{type(exc).__name__}: {exc}")

    def peak(self, key: str):
        values = [s[key] for s in self.samples if s.get(key) is not None]
        return max(values) if values else None

    def any(self, key: str) -> bool:
        return any(s.get(key) is not None for s in self.samples)


def counts(conn, user_id: int) -> tuple[int, int, int]:
    """(search_history 行数, search_count 合计, search_log 行数)"""
    history = conn.execute(
        "SELECT count(*), coalesce(sum(search_count), 0) FROM search_history"
        " WHERE user_id = %s", (user_id,)).fetchone()
    logs = conn.execute(
        "SELECT count(*) FROM search_log WHERE user_id = %s", (user_id,)).fetchone()
    return history[0], history[1], logs[0]


async def run_batch(args, headers: dict, count: int, warmup: bool = False) -> dict:
    """打 count 个请求；warmup=True 时只发不记。"""
    latencies: list[float] = []
    statuses: Counter = Counter()
    errors: Counter = Counter()
    samples: list[str] = []
    sem = asyncio.Semaphore(args.concurrency)
    limits = httpx.Limits(max_connections=args.concurrency + 4)

    async with httpx.AsyncClient(base_url=args.base_url, timeout=args.timeout,
                                 limits=limits) as client:

        async def one(i: int) -> None:
            async with sem:
                started = time.perf_counter()
                try:
                    if args.mode == "login":
                        res = await client.post("/api/v1/auth/token", data={
                            "username": args.username, "password": args.password})
                    else:
                        res = await client.post(PATH_BY_API[args.api],
                                                json=body_for(i, args),
                                                headers=headers)
                    status, text = res.status_code, res.text[:200]
                except Exception as exc:                    # noqa: BLE001
                    status = 0
                    text = f"{type(exc).__name__}: {exc}"
                    errors[type(exc).__name__] += 1
                if warmup:
                    return
                latencies.append((time.perf_counter() - started) * 1000)
                statuses[status] += 1
                if status != 200 and len(samples) < 5:
                    samples.append(f"{status} {text}")

        started = time.perf_counter()
        await asyncio.gather(*(one(i) for i in range(count)))
        wall = time.perf_counter() - started

    return {"latencies": latencies, "statuses": statuses, "errors": errors,
            "samples": samples, "wall": wall, "requests": count}


def report_client(args, batches: list[dict]) -> dict:
    latencies = [v for b in batches for v in b["latencies"]]
    statuses: Counter = Counter()
    errors: Counter = Counter()
    samples: list[str] = []
    for b in batches:
        statuses.update(b["statuses"])
        errors.update(b["errors"])
        samples += b["samples"]
    wall = sum(b["wall"] for b in batches)

    print("\n== 客户端 ==")
    print(f"接口 {PATH_BY_API[args.api]}  请求 {len(latencies)}  并发 {args.concurrency}"
          f"  模式 {args.mode}")
    print("状态码 " + ("  ".join(f"{code}×{n}" for code, n in sorted(statuses.items()))
                      or "无"))
    print("异常 " + ("  ".join(f"{name}×{n}" for name, n in errors.most_common()) or "无"))
    lat = latency_block(latencies)
    if lat:
        print(f"延迟 ms  p50 {lat['p50']:.0f}  p90 {lat['p90']:.0f}  p95 {lat['p95']:.0f}"
              f"  p99 {lat['p99']:.0f}  max {lat['max']:.0f}  均值 {lat['mean']:.0f}")
    for line in samples[:5]:
        print(f"  非 200 例：{line}")

    throughput = len(latencies) / wall if wall else 0.0
    print(f"墙钟 {wall:.1f}s  吞吐 {throughput:.1f} req/s")

    failed = sum(n for code, n in statuses.items() if code != 200) + sum(errors.values())
    rate = failed / len(latencies) if latencies else 0.0
    if rate > 0.01:
        print(f"  !! 错误率 {rate:.1%} > 1%，按规矩先定位再继续")
    return {"statuses": {str(k): v for k, v in statuses.items()},
            "errors": dict(errors), "latency": lat, "throughput": throughput,
            "wall": wall, "error_rate": rate, "samples": samples[:5]}


def report_server(sampler: Sampler, before, after) -> dict:
    print("\n== 服务端 ==")
    for note in sampler.errors:
        print(f"  {note}")
    print(f"PG 后端峰值 {sampler.peak('pg_backends')}（应用池上限 {POOL_MAX}）"
          f"  行锁等待峰值 {sampler.peak('pg_lock_waits')}")
    if sampler.any("es_queue"):
        print(f"ES search 队列峰值 {sampler.peak('es_queue')}"
              f"  rejected {sampler.peak('es_rejected')}"
              f"  并发峰值 {sampler.peak('es_active')}")
    if sampler.any("enc_queue"):
        print(f"编码服务 队列峰值 {sampler.peak('enc_queue')}"
              f"  单批峰值 {sampler.peak('enc_batch')}")
    if sampler.rss:
        first, last = sampler.rss[0], sampler.rss[-1]
        peak = max(r["rss_mb"] for r in sampler.rss)
        print(f"python 进程 RSS {first['rss_mb']:.0f} → {last['rss_mb']:.0f} MB"
              f"（峰值 {peak:.0f}，{last['procs']} 个进程）"
              f"  句柄 {first['handles']} → {last['handles']}")

    history_before, count_before, log_before = before
    history_after, count_after, log_after = after
    print("\n== 落库核对 ==")
    print(f"search_log      {log_before} → {log_after}（新增 {log_after - log_before}）")
    print(f"search_history  {history_before} → {history_after}"
          f"（新增 {history_after - history_before} 行）")
    print(f"search_count    {count_before} → {count_after}"
          f"（合计 {count_after - count_before}）")
    return {"pg_peak_backends": sampler.peak("pg_backends"),
            "pg_peak_lock_waits": sampler.peak("pg_lock_waits"),
            "es_peak_queue": sampler.peak("es_queue"),
            "es_peak_rejected": sampler.peak("es_rejected"),
            "es_peak_active": sampler.peak("es_active"),
            "enc_peak_queue": sampler.peak("enc_queue"),
            "enc_peak_batch": sampler.peak("enc_batch"),
            "rss_peak_mb": max((r["rss_mb"] for r in sampler.rss), default=None),
            "rss_start_mb": sampler.rss[0]["rss_mb"] if sampler.rss else None,
            "rss_end_mb": sampler.rss[-1]["rss_mb"] if sampler.rss else None,
            "handles_start": sampler.rss[0]["handles"] if sampler.rss else None,
            "handles_end": sampler.rss[-1]["handles"] if sampler.rss else None,
            "sampler_errors": sampler.errors,
            "search_log": [log_before, log_after],
            "search_history": [history_before, history_after],
            "search_count": [count_before, count_after]}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已写入 {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api", choices=["reports", "objects"], default="reports")
    parser.add_argument("--username", default="stress1")
    parser.add_argument("--password", default="stresspass123")
    parser.add_argument("--requests", type=int, default=200,
                        help="每轮请求数（--soak 时是每轮的量）")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--mode", choices=["same", "paging", "mixed", "login"],
                        default="mixed")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--warmup", type=int, default=20, help="热身请求数，不计入统计")
    parser.add_argument("--soak", type=float, default=0.0, help="长跑分钟数，0 = 只跑一轮")
    parser.add_argument("--interval", type=float, default=1.0, help="采样间隔秒")
    parser.add_argument("--rss-every", type=float, default=30.0,
                        help="RSS/句柄采样间隔秒，0 = 关")
    parser.add_argument("--match-mode", choices=["or", "and", "phrase"], default="or",
                        help="报告接口的 mode 参数")
    parser.add_argument("--time-weight", type=float, default=0.0, help="报告接口的时间衰减权重")
    parser.add_argument("--layout", choices=["横版", "竖版"], default=None)
    parser.add_argument("--days", type=int, default=0, help="只看最近 N 天发布的报告")
    parser.add_argument("--json", action="store_true", help="结果写 JSON")
    parser.add_argument("--out", default=None,
                        help="JSON 路径，默认 stress/stress-<run-id>.json")
    args = parser.parse_args()

    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")

    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        res = client.post("/api/v1/auth/register", json={
            "username": args.username, "password": args.password})
        print(f"注册 {args.username}: {res.status_code}"
              f"{'（已存在）' if res.status_code == 409 else ''}")
        headers: dict = {}
        user_id = None
        if args.mode != "login":
            res = client.post("/api/v1/auth/token", data={
                "username": args.username, "password": args.password})
            res.raise_for_status()
            headers = {"Authorization": f"Bearer {res.json()['access_token']}"}
            user_id = client.get("/api/v1/auth/me", headers=headers).json()["id"]

    conn = psycopg.connect(pg_dsn(), autocommit=True)
    before = counts(conn, user_id) if user_id is not None else (0, 0, 0)
    print(f"用户 id={user_id}  基线 {before}")

    sampler = Sampler(interval=args.interval, rss_every=args.rss_every)
    sampler.start()
    batches: list[dict] = []
    rounds: list[dict] = []
    try:
        if args.warmup:
            asyncio.run(run_batch(args, headers, args.warmup, warmup=True))
            print(f"热身 {args.warmup} 个请求完成")

        if args.soak > 0:
            deadline = time.perf_counter() + args.soak * 60
            while time.perf_counter() < deadline:
                batch = asyncio.run(run_batch(args, headers, args.requests))
                batches.append(batch)
                lat = latency_block(batch["latencies"])
                failed = sum(batch["errors"].values()) + sum(
                    n for code, n in batch["statuses"].items() if code != 200)
                rounds.append({"wall": batch["wall"], "latency": lat,
                               "failed": failed, "requests": batch["requests"]})
                print(f"  轮 {len(rounds)}  吞吐 {batch['requests'] / batch['wall']:.1f} req/s"
                      f"  p50 {lat.get('p50', 0):.0f}  p95 {lat.get('p95', 0):.0f}"
                      f"  错误 {failed}")
                if failed > batch["requests"] * 0.01:
                    print("  !! 错误率 > 1%，中止长跑")
                    break
        else:
            batches.append(asyncio.run(run_batch(args, headers, args.requests)))
    finally:
        sampler.stop_flag.set()
        sampler.join(timeout=3)

    after = counts(conn, user_id) if user_id is not None else (0, 0, 0)
    conn.close()

    client_block = report_client(args, batches)
    server_block = report_server(sampler, before, after)
    if rounds:
        print("\n== 长跑漂移（每轮）==")
        for i, r in enumerate(rounds, 1):
            print(f"  轮 {i}  {r['wall']:.1f}s  p50 {r['latency'].get('p50', 0):.0f}"
                  f"  p95 {r['latency'].get('p95', 0):.0f}  错误 {r['failed']}")

    if args.json:
        out = Path(args.out) if args.out else ROOT / "stress" / f"stress-{run_id}.json"
        write_json(out, {"run_id": run_id, "started_at": started_at,
                         "config": vars(args), "client": client_block,
                         "server": server_block, "rounds": rounds})


if __name__ == "__main__":
    main()
