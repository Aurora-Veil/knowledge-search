"""检索缓存预热 + Redis 容量测量。

压测前先把 ramp_load.py 会打到的检索集合预热到 80%，这样高并发阶段大部分
请求走缓存命中的短路径，剩下 20% 仍走 ES，两条路径都在压。

预热完顺带量三件事：
    1. Redis 里到底有多少个缓存键（应等于预热的不同检索数）
    2. 每个键占多少字节，据此推算 256MB 上限能装多少条
    3. 同一请求第二次的热命中延迟，以及**命中返回值与首次是否逐字节相同**

用法（仓库根目录）：
    $env:PYTHONIOENCODING='utf-8'; $env:PYTHONPATH=(Get-Location).Path
    python stress/scripts/cache_warm.py
    python stress/scripts/cache_warm.py --fraction 0.8
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx                                                    # noqa: E402
from ramp_load import TOPICS                                    # noqa: E402

BASE = "http://127.0.0.1:8000"
USERNAME = "stress1"
PASSWORD = "stresspass123"
SIZE = 20
PREFIX = "oirf:report:"


def redis_password() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*REDIS_PASSWORD\s*=\s*(.+?)\s*$", line)
        if m:
            return m.group(1)
    raise SystemExit("REDIS_PASSWORD 不在 .env 里")


_PW = redis_password()


def rcli(*args: str) -> str:
    """走 docker exec 调 redis-cli，省掉本机装 redis 包。"""
    res = subprocess.run(["docker", "exec", "redis", "redis-cli",
                          "--no-auth-warning", "-a", _PW, *args],
                         capture_output=True, text=True, timeout=30)
    return res.stdout.strip()


def info_memory() -> dict[str, int]:
    out: dict[str, int] = {}
    for line in rcli("info", "memory").splitlines():
        if ":" in line and not line.startswith("#"):
            key, _, value = line.partition(":")
            if value.isdigit():
                out[key] = int(value)
    return out


def cache_keys() -> list[str]:
    raw = rcli("keys", PREFIX + "*")
    return sorted(k for k in raw.splitlines() if k)


def login() -> dict:
    with httpx.Client(base_url=BASE, timeout=30) as client:
        res = client.post("/api/v1/auth/register",
                          json={"username": USERNAME, "password": PASSWORD})
        print(f"注册 {USERNAME}: {res.status_code}"
              f"{'（已存在）' if res.status_code == 409 else ''}")
        res = client.post("/api/v1/auth/token",
                          data={"username": USERNAME, "password": PASSWORD})
        res.raise_for_status()
        return {"Authorization": f"Bearer {res.json()['access_token']}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fraction", type=float, default=0.8,
                    help="预热检索集合的比例，默认 0.8")
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()

    n_warm = max(1, int(round(len(TOPICS) * args.fraction)))
    warm, cold = TOPICS[:n_warm], TOPICS[n_warm:]
    print(f"\n检索集合 {len(TOPICS)} 条（q × size={SIZE}，page=1）")
    print(f"预热 {len(warm)} 条（{args.fraction:.0%}），留冷 {len(cold)} 条：{cold}\n")

    headers = login()

    db0 = int(rcli("dbsize"))
    mem0 = info_memory()
    print(f"预热前：DBSIZE={db0}  used_memory={mem0['used_memory']}  "
          f"dataset={mem0['used_memory_dataset']}\n")

    first: dict[str, dict] = {}
    body_bytes: dict[str, int] = {}
    lat_cold: list[float] = []

    print(f"{'#':>3} {'q':<12} {'状态':>4} {'耗时ms':>8} {'响应字节':>8} {'total':>7}")
    with httpx.Client(base_url=BASE, timeout=args.timeout) as client:
        for i, q in enumerate(warm):
            t0 = time.perf_counter()
            res = client.post("/api/v1/reports/search",
                              json={"q": q, "size": SIZE}, headers=headers)
            ms = (time.perf_counter() - t0) * 1000
            lat_cold.append(ms)
            if res.status_code == 200:
                payload = res.json()
                first[q] = payload
                body_bytes[q] = len(res.content)
                print(f"{i:>3} {q:<12} {res.status_code:>4} {ms:>8.0f} "
                      f"{len(res.content):>8} {payload.get('total'):>7}")
            else:
                print(f"{i:>3} {q:<12} {res.status_code:>4} {ms:>8.0f}  {res.text[:80]}")

    db1 = int(rcli("dbsize"))
    mem1 = info_memory()
    print(f"\n预热后：DBSIZE={db1}（+{db1 - db0}）  used_memory={mem1['used_memory']} "
          f"（+{mem1['used_memory'] - mem0['used_memory']}）  "
          f"dataset={mem1['used_memory_dataset']}（+{mem1['used_memory_dataset'] - mem0['used_memory_dataset']}）")

    keys = cache_keys()
    print(f"键前缀 {PREFIX} 命中 {len(keys)} 个（预期 {len(warm)}）")
    usage: dict[str, int] = {}
    ttls: list[int] = []
    for key in keys:
        usage[key] = int(rcli("memory", "usage", key) or 0)
        ttls.append(int(rcli("ttl", key) or -1))

    if usage:
        total_bytes = sum(usage.values())
        avg = total_bytes / len(usage)
        payload_avg = sum(body_bytes.values()) / len(body_bytes) if body_bytes else 0
        print(f"\n{'键内存合计':<14}{total_bytes:>10} B")
        print(f"{'单键均值':<14}{avg:>10.0f} B   最大 {max(usage.values())} B   "
              f"最小 {min(usage.values())} B")
        print(f"{'响应体均值':<14}{payload_avg:>10.0f} B   （键内存 / 响应体 = "
              f"{avg / payload_avg:.2f}×）" if payload_avg else "")
        print(f"{'TTL 范围':<14}{min(ttls):>10} ~ {max(ttls)} s（应都在距离今夜 0 点之内）")
        print(f"\n256MB 上限按此均值可容纳约 {int(256 * 1024 * 1024 / avg):,} 条")

    # 热命中：同一条请求再打一遍，比对延迟与返回值
    print(f"\n{'#':>3} {'q':<12} {'状态':>4} {'命中ms':>8} {'相同':>5}")
    lat_hit: list[float] = []
    same = 0
    with httpx.Client(base_url=BASE, timeout=args.timeout) as client:
        for i, q in enumerate(warm):
            t0 = time.perf_counter()
            res = client.post("/api/v1/reports/search",
                              json={"q": q, "size": SIZE}, headers=headers)
            ms = (time.perf_counter() - t0) * 1000
            lat_hit.append(ms)
            ok = res.status_code == 200 and res.json() == first.get(q)
            same += bool(ok)
            print(f"{i:>3} {q:<12} {res.status_code:>4} {ms:>8.1f} "
                  f"{'是' if ok else '否':>5}")

    def pct(values: list[float], p: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))]

    print(f"\n冷路径（走 ES）  n={len(lat_cold):<3} 均值 {sum(lat_cold) / len(lat_cold):>7.0f} ms  "
          f"p50 {pct(lat_cold, 50):>7.0f} ms  max {max(lat_cold):>7.0f} ms")
    print(f"热命中（走缓存） n={len(lat_hit):<3} 均值 {sum(lat_hit) / len(lat_hit):>7.0f} ms  "
          f"p50 {pct(lat_hit, 50):>7.0f} ms  max {max(lat_hit):>7.0f} ms")
    print(f"命中返回值与首次逐字段相同：{same}/{len(warm)}")

    m = re.search(r"keyspace_hits:(\d+)", rcli("info", "stats"))
    if m:
        print(f"Redis keyspace_hits 累计：{m.group(1)}")

    return 0 if same == len(warm) and len(keys) == len(warm) else 1


if __name__ == "__main__":
    sys.exit(main())
