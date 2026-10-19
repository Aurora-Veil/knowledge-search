"""混合检索压测：检索词、翻页、筛选按真实用户的形态随机组合。

和 ramp_load.py 的区别：那边只有 20 条固定检索词、size 固定 20，第一轮就把缓存
装满，测出来的是纯命中路径。这边用 build_queries.py 从 example/reports.csv 抽出的
词库，按 7 种形态组查询，请求形状（翻页深度、mode、time_weight、时间范围、版式）
按 static/report.js 里页面的真实写法随机组合，缓存命中率会掉到接近真实的水平。

7 种形态：
    keyword   1-2 个同板块词                储能 电池
    synonym   词 + 它的近义词               人工智能 AI
    cross     两个不同板块的词              化妆品 人工智能
    title     报告标题去掉年份/版本          AI环境下的营销最佳应用实践
    multi     同板块 3-4 个词               新能源汽车 动力电池 充电桩
    broad     单个泛词                      人工智能
    filtered  词 + 行业/版式过滤            储能 [industry=储能]

请求形状对齐 static/report.js（页面的真实写法）：
    size        固定 20：页面把 PAGE_SIZE = 20 写死，没有让用户选
    page        会话式翻页：73% 的会话只看第 1 页；其余会话按 2 / 3 / 4 / 5-10 的
                深度逐页往下翻，**某页不足 20 条就停**——页面的「下一页」在不满页
                时是灰的（renderPager 里 hasNext = hits.length === PAGE_SIZE）。
                合起来约 80% 的请求落在第 1 页，翻到 5 页以上约 1.5%。
                上限 MAX_PAGE = 10，因为 RESULT_WINDOW = 200、size = 20。
    mode        or(82%) / and(12%) / phrase(6%)，且始终显式带上（页面下拉框没有空选项）
    time_weight 不传(70%) / 0.1(10%) / 0.2(10%) / 0.35(10%)——页面下拉框只有这四档
    时间范围    全部(55%) / 近一年(15%) / 近三年(10%) / 近五年(5%) / 指定年份(15%)
                相对区间只卡下界，指定年份卡整年，与 periodRange() 一致
    layout      全部版式(88%) / 横版(6%) / 竖版(6%)
    不发 highlight=false：页面从不发这个字段

缓存协议（默认 --reset-cache flush+warm）：
    每档开测前把报表缓存恢复成同一个基线，否则档与档的起点不同、结果不可比：
        1) 删掉 oirf:report:*（不清 Session 等其他键）
        2) 用固定种子发 --warm-requests 条首页请求（默认 4000，并发 64）
        3) 读 dbsize / used_memory 校验，作为该档基线记进结果 JSON
    4000 条 ≈ 4000 键 ≈ 55 MB，占 256 MB 容量的 22%。一档 120 s 只会写 1.6 万键，
    所以基线在整档内基本不会被 LRU 冲掉。
    --reset-cache none 保留旧行为（不清缓存，档与档之间自然继承）。

用法（仓库根目录）：
    $env:PYTHONIOENCODING='utf-8'; $env:PYTHONPATH=(Get-Location).Path
    python stress/build_queries.py                        # 词库，改了 CSV 才需要重跑
    python stress/scripts/ramp_mixed.py --levels 64 --duration 60 --out stress/archive/run/mix.json
    python stress/scripts/ramp_mixed.py --levels 32,64,128,256,512 --procs 8 `
        --duration 120 --timeout 150 --tag ladder --out stress/archive/run/ladder.json
"""
from __future__ import annotations

import argparse
import asyncio
import bisect
import json
import os
import random
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx                                                     # noqa: E402
from ramp_load import CpuSampler, NET_ERRORS, login, pct         # noqa: E402

QUERIES = ROOT / "stress" / "queries.json"

KINDS = ("keyword", "synonym", "cross", "title", "multi", "broad", "filtered")
# 长查询（title）只留 7%：真实检索以短词为主，整条标题粘贴是少数行为
KIND_W = (0.34, 0.14, 0.10, 0.07, 0.08, 0.15, 0.12)

# --- 直方图：合并多进程结果时不能平均百分位，只能合原始分布 ---
H_FINE, H_MID, H_STEP = 10_000, 60_000, 100
H_N = H_FINE + (H_MID - H_FINE) // H_STEP + 1

# 形态/页码用 10 ms 一格的粗直方图，够比较形状，体积小一个数量级
H2_FINE, H2_STEP = 10_000, 100
H2_N = H2_FINE // 10 + (H_MID - H2_FINE) // H2_STEP + 1


def h_index(ms: float) -> int:
    if ms < H_FINE:
        return max(0, int(ms))
    if ms < H_MID:
        return H_FINE + int((ms - H_FINE) / H_STEP)
    return H_N - 1


def h_value(i: int) -> float:
    return float(i) if i < H_FINE else H_FINE + (i - H_FINE) * H_STEP


def h2_index(ms: float) -> int:
    if ms < H2_FINE:
        return max(0, int(ms // 10))
    if ms < H_MID:
        return H2_FINE // 10 + int((ms - H2_FINE) / H2_STEP)
    return H2_N - 1


def h2_value(i: int) -> float:
    return i * 10.0 if i < H2_FINE // 10 else H2_FINE + (i - H2_FINE // 10) * H2_STEP


def h_pct(counts: list[int], p: float, value=h_value) -> float:
    total = sum(counts)
    if not total:
        return 0.0
    target = p / 100 * (total - 1)
    seen = 0
    for i, c in enumerate(counts):
        if c and seen + c > target:
            return value(i)
        seen += c
    return value(len(counts) - 1)


def h_sum(dst: list[int], src: list[int]) -> None:
    for i, c in enumerate(src):
        if c:
            dst[i] += c


class Stats:
    """一档（一个并发）的累计量。"""

    __slots__ = ("concurrency", "duration", "n", "issued", "wall", "sum_ms", "max_ms",
                 "hist", "statuses", "errors", "degraded", "hang", "empty",
                 "kinds", "pages", "modes", "tw", "cpu_cores")

    def __init__(self, concurrency: int, duration: float) -> None:
        self.concurrency = concurrency
        self.duration = duration
        self.n = 0
        self.issued = 0
        self.wall = 0.0
        self.sum_ms = 0.0
        self.max_ms = 0.0
        self.hist = [0] * H_N
        self.statuses: Counter = Counter()
        self.errors: Counter = Counter()
        self.degraded = 0
        self.hang = 0
        self.empty = 0
        self.kinds: dict[str, dict] = {
            k: {"n": 0, "empty": 0, "sum_ms": 0.0, "hist": [0] * H2_N} for k in KINDS
        }
        self.pages: dict[str, dict] = {
            str(p): {"n": 0, "empty": 0, "sum_ms": 0.0, "hist": [0] * H2_N}
            for p in range(1, MAX_PAGE + 1)
        }
        self.modes: Counter = Counter()
        self.tw: Counter = Counter()
        self.cpu_cores = 0.0

    def add(self, ms: float, status: int, err: str | None, degraded: bool,
            empty: bool, kind: str, page: int, mode: str, tw: str) -> None:
        self.n += 1
        self.sum_ms += ms
        self.max_ms = max(self.max_ms, ms)
        self.hist[h_index(ms)] += 1
        self.statuses[status] += 1
        self.modes[mode] += 1
        self.tw[tw] += 1
        if ms > 10_000:
            self.hang += 1
        if err:
            self.errors[err] += 1
        if degraded:
            self.degraded += 1
        if empty:
            self.empty += 1
        k = self.kinds.get(kind)
        if k is not None:
            k["n"] += 1
            k["sum_ms"] += ms
            k["empty"] += int(empty)
            k["hist"][h2_index(ms)] += 1
        p = self.pages.get(str(page))
        if p is not None:
            p["n"] += 1
            p["sum_ms"] += ms
            p["empty"] += int(empty)
            p["hist"][h2_index(ms)] += 1

    def summary(self) -> dict:
        failed = sum(v for k, v in self.statuses.items() if k != 200)
        return {
            "concurrency": self.concurrency,
            "duration_s": round(self.wall, 2),
            "requests": self.n,
            "issued": self.issued,
            "throughput": round(self.n / self.wall, 2) if self.wall else 0.0,
            "statuses": {str(k): v for k, v in sorted(self.statuses.items())},
            "errors": dict(self.errors),
            "failed": failed,
            "degraded": self.degraded,
            "empty": self.empty,
            "hang_gt_10s": self.hang,
            "mean": round(self.sum_ms / self.n, 1) if self.n else 0.0,
            "max": round(self.max_ms, 1),
            "cpu_cores": round(self.cpu_cores, 3),
            "hist": self.hist,
            "kinds": self.kinds,
            "pages": self.pages,
            "modes": dict(self.modes),
            "time_weight": dict(self.tw),
        }


# --- 检索词库与查询组合 ---

class Catalog:
    def __init__(self, data: dict, rng: random.Random, size: int) -> None:
        self.terms = data["terms"]
        self.aliases = [tuple(a) for a in data["aliases"]]
        self.titles = data["titles"]
        self.by_sector: dict[str, list[str]] = defaultdict(list)
        self.leaf_sector: dict[str, str] = {}
        for t in self.terms:
            self.by_sector[t["s"]].append(t["t"])
            self.leaf_sector[t["t"]] = t["s"]
        self.by_sector = {s: v for s, v in self.by_sector.items() if len(v) >= 3}
        self.sectors = list(self.by_sector)
        self.top = [t["t"] for t in sorted(self.terms, key=lambda t: -t["n"])[:200]]
        # 行业过滤用叶子词：ES 里 industry 存的就是这些分段，term 能直接命中
        self.filter_leaves = [t for t in self.leaf_sector if self.by_sector.get(self.leaf_sector[t])]

        self.pools: dict[str, list[tuple[str, str | None]]] = {k: [] for k in KINDS}
        seen: dict[str, set[str]] = {k: set() for k in KINDS}
        guard = size * 40
        while sum(len(v) for v in self.pools.values()) < size and guard:
            guard -= 1
            kind = rng.choices(KINDS, KIND_W)[0]
            item = self._compose(kind, rng)
            if item and item[0] not in seen[kind]:
                seen[kind].add(item[0])
                self.pools[kind].append(item)
        # 每种形态内部按 Zipf 抽：头部查询反复出现，长尾只出现几次
        self.cum = {k: _zipf([0] * len(v)) for k, v in self.pools.items()}

    def _compose(self, kind: str, rng: random.Random) -> tuple[str, str | None] | None:
        if kind == "title":
            return rng.choice(self.titles), None
        if kind == "synonym":
            a, b = rng.choice(self.aliases)
            return f"{a} {b}", None
        if kind == "broad":
            return rng.choice(self.top), None
        if kind == "cross" and len(self.sectors) >= 2:
            s1, s2 = rng.sample(self.sectors, 2)
            return f"{rng.choice(self.by_sector[s1])} {rng.choice(self.by_sector[s2])}", None
        if kind == "multi":
            sector = rng.choice(self.sectors)
            pool = self.by_sector[sector]
            return " ".join(rng.sample(pool, min(3, len(pool)))), None
        if kind == "filtered":
            # 先定行业，查询词落在该行业里，模拟"筛完再在结果里搜"的真实顺序
            leaf = rng.choice(self.filter_leaves)
            pool = self.by_sector[self.leaf_sector[leaf]]
            if rng.random() < 0.4:
                return leaf, leaf
            return f"{leaf} {rng.choice(pool)}", leaf
        t1 = rng.choice(self.terms)["t"]
        sector = self.leaf_sector.get(t1)
        if sector and rng.random() < 0.45:
            others = [t for t in self.by_sector.get(sector, []) if t != t1]
            if others:
                return f"{t1} {rng.choice(others)}", None
        return t1, None

    def sample(self, rng: random.Random) -> tuple[str, str, str | None]:
        kind = rng.choices(KINDS, KIND_W)[0]
        pool = self.pools[kind]
        if not pool:
            kind, pool = "keyword", self.pools["keyword"]
        cum = self.cum[kind]
        x = rng.random() * cum[-1]
        i = min(bisect.bisect_left(cum, x), len(pool) - 1)
        q, extra = pool[i]
        return q, kind, extra


def _zipf(_unused: list) -> list[float]:
    """1/(i+8)^1.05 的累积和：给目录里的每条查询一个 Zipf 权重。"""
    cum: list[float] = []
    acc = 0.0
    for i in range(len(_unused)):
        acc += 1.0 / (i + 8) ** 1.05
        cum.append(acc)
    return cum or [1.0]


# --- 请求体 ---

# --- 请求体：形状照抄 static/report.js ---

PAGE_SIZE = 20                              # 页面写死，没让用户选
MAX_PAGE = 200 // PAGE_SIZE                 # RESULT_WINDOW / size → 10
P_DEEP = 0.17                               # 17% 的会话会往下翻，合起来 ~80% 请求停在第 1 页
                                            # 首轮用 0.27 实测只到 71.7%：向量命中会把页填满，
                                            # 「不满页就停」几乎不触发，深度基本按抽到的走
DEEP_W = ((2, 0.65), (3, 0.20), (4, 0.10), (5, 0.05))   # 5 表示 5..10 均匀
TW_W = ((0.0, 0.70), (0.1, 0.10), (0.2, 0.10), (0.35, 0.10))   # 0.0 = 不发该字段
YEARS = (2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026)


def session_depth(rng: random.Random) -> int:
    """这次会话往下翻到第几页。73% 只停在第 1 页。"""
    if rng.random() >= P_DEEP:
        return 1
    d = rng.choices([w[0] for w in DEEP_W], [w[1] for w in DEEP_W])[0]
    return rng.randint(5, MAX_PAGE) if d == 5 else d


def _years_ago(today: date, n: int) -> str:
    try:
        return today.replace(year=today.year - n).isoformat()
    except ValueError:                      # 2 月 29 日
        return today.replace(year=today.year - n, day=28).isoformat()


def make_body(q: str, kind: str, extra: str | None, rng: random.Random,
              today: date) -> tuple[dict, str, str, int]:
    """返回 (第 1 页的 body, mode, time_weight 标签, 会话翻页深度)。"""
    mode = rng.choices(("or", "and", "phrase"), (0.82, 0.12, 0.06))[0]
    body: dict = {"q": q, "mode": mode, "page": 1, "size": PAGE_SIZE}

    tw_val = rng.choices([w[0] for w in TW_W], [w[1] for w in TW_W])[0]
    tw = "0" if not tw_val else f"{tw_val:g}"
    if tw_val:
        body["time_weight"] = tw_val

    r = rng.random()
    if r < 0.55:
        pass                                                # 全部时间
    elif r < 0.70:
        body["publish_date_from"] = _years_ago(today, 1)    # 近一年，只卡下界
    elif r < 0.80:
        body["publish_date_from"] = _years_ago(today, 3)
    elif r < 0.85:
        body["publish_date_from"] = _years_ago(today, 5)
    else:
        year = rng.choice(YEARS)
        body["publish_date_from"] = f"{year}-01-01"
        body["publish_date_to"] = f"{year}-12-31"

    if rng.random() < 0.12:
        body["layout"] = rng.choice(("横版", "竖版"))

    if kind == "filtered":
        body["industry"] = [extra]

    return body, mode, tw, session_depth(rng)


def _credentials(args) -> tuple[dict, int]:
    token = os.environ.get("RAMP_TOKEN")
    if token:
        return ({"Authorization": f"Bearer {token}"},
                int(os.environ.get("RAMP_USER_ID") or 0))
    return login(args.base_url, args.username, args.password, quiet=True)


async def drive(client: httpx.AsyncClient, stats: Stats, args, headers: dict,
                catalog: Catalog, rng: random.Random, today: date) -> None:
    sem = asyncio.Semaphore(stats.concurrency)
    deadline = time.perf_counter() + stats.duration

    async def one_session() -> None:
        """一次会话：同一个词、同一组筛选条件，从第 1 页往下翻到深度或翻不动为止。"""
        async with sem:
            q, kind, extra = catalog.sample(rng)
            body, mode, tw, depth = make_body(q, kind, extra, rng, today)
            for page in range(1, depth + 1):
                body["page"] = page
                started = time.perf_counter()
                status, err, degraded, empty, nhits = 0, None, False, False, 0
                try:
                    res = await client.post("/api/v1/reports/search", json=body,
                                            headers=headers)
                    status = res.status_code
                    if status == 200:
                        payload = res.json()
                        degraded = bool(payload.get("degraded"))
                        empty = int(payload.get("total") or 0) == 0
                        nhits = len(payload.get("hits") or [])
                except Exception as exc:                                # noqa: BLE001
                    name = type(exc).__name__
                    err = name if name in NET_ERRORS else f"other:{name}"
                ms = (time.perf_counter() - started) * 1000
                stats.issued += 1
                stats.add(ms, status, err, degraded, empty, kind, page, mode, tw)
                # 出错就收手；这一页没装满 20 条，用户点不动「下一页」
                if err or nhits < PAGE_SIZE:
                    break

    async def worker() -> None:
        while time.perf_counter() < deadline:
            await one_session()

    tasks = [asyncio.create_task(worker()) for _ in range(stats.concurrency)]
    t0 = time.perf_counter()
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        stats.wall = time.perf_counter() - t0


def _wait_go(d: Path, idx: int) -> None:
    """等父进程把这一档的缓存基线做好（先把 go{idx} 文件放下来）。"""
    go = d / f"go{idx}"
    limit = time.time() + 900
    while not go.exists():
        if time.time() > limit:
            raise SystemExit(f"等预热信号 go{idx} 超时")
        time.sleep(0.2)


def run_shard(args) -> int:
    data = json.loads(Path(args.queries).read_text(encoding="utf-8"))
    catalog = Catalog(data, random.Random(args.seed), args.catalog)
    headers, user_id = _credentials(args)
    levels = [int(x) for x in args.levels.split(",") if x.strip()]
    today = date.today()
    shard_idx, shard_total = (int(x) for x in (args.shard or "0/1").split("/"))
    if shard_total == 1:
        print(f"词库 {sum(len(v) for v in catalog.pools.values())} 条"
              f"（{len(data['terms'])} 词 / {len(data['aliases'])} 组近义词 / "
              f"{len(data['titles'])} 条标题），用户 id={user_id}", flush=True)
        print(f"{'并发':>6} {'时长':>6} {'请求':>8} {'吞吐':>8} {'p50':>7} {'p95':>7} "
              f"{'p99':>7} {'空结果':>7} {'错误':>5} {'降级':>5} {'客户端核':>8}", flush=True)

    phases: list[dict] = []
    async def run() -> None:
        limits = httpx.Limits(max_connections=max(levels) + 32,
                              max_keepalive_connections=max(levels) + 32)
        async with httpx.AsyncClient(base_url=args.base_url, timeout=args.timeout,
                                     limits=limits) as client:
            for idx, concurrency in enumerate(levels):
                if args.barrier_dir:
                    _wait_go(Path(args.barrier_dir), idx)
                stats = Stats(concurrency, float(args.duration))
                sampler = CpuSampler().start()
                # 档位必须进种子：否则每档重放同一串查询，上一档刚写的缓存键
                # 会被下一档原样命中，跨档命中率被放大（见 report-mixed.md §4）
                rng = random.Random(args.seed + 7919 * (shard_idx + 1) + 104729 * concurrency)
                try:
                    await drive(client, stats, args, headers, catalog, rng, today)
                finally:
                    sampler.stop()
                    stats.cpu_cores = sampler.cores()
                block = stats.summary()
                phases.append(block)
                if shard_total == 1:
                    print(f"{concurrency:>6} {block['duration_s']:>6.0f} "
                          f"{block['requests']:>8} {block['throughput']:>8.1f} "
                          f"{h_pct(block['hist'], 50):>7.0f} {h_pct(block['hist'], 95):>7.0f} "
                          f"{h_pct(block['hist'], 99):>7.0f} "
                          f"{block['empty'] / max(block['requests'], 1):>7.1%} "
                          f"{block['failed']:>5} {block['degraded']:>5} "
                          f"{block['cpu_cores']:>5.2f}", flush=True)
                if args.barrier_dir:
                    (Path(args.barrier_dir) / f"done{idx}-{shard_idx:02d}").touch()

    asyncio.run(run())
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"tag": args.tag, "seed": args.seed, "phases": phases},
                              ensure_ascii=False), encoding="utf-8")
    if shard_total > 1:
        print(f"[{shard_idx}/{shard_total}] → {out}", flush=True)
    else:
        print_breakdown(phases)
    return 0


async def _warm_async(args, catalog: Catalog, headers: dict, today: date,
                      rng: random.Random) -> tuple[int, int]:
    """按固定种子发 warm_requests 条首页请求，把缓存填成一个固定基线。"""
    limits = httpx.Limits(max_connections=args.warm_concurrency + 8,
                          max_keepalive_connections=args.warm_concurrency + 8)
    sent = ok = 0
    async with httpx.AsyncClient(base_url=args.base_url, timeout=args.timeout,
                                 limits=limits) as client:
        async def worker() -> None:
            nonlocal sent, ok
            while sent < args.warm_requests:
                sent += 1                       # 单线程，检查与自增之间没有 await
                q, kind, extra = catalog.sample(rng)
                body, _mode, _tw, _depth = make_body(q, kind, extra, rng, today)
                body["page"] = 1                # 预热只填第 1 页，占真实流量八成
                try:
                    res = await client.post("/api/v1/reports/search", json=body,
                                            headers=headers)
                    if res.status_code == 200:
                        ok += 1
                except Exception:                                  # noqa: BLE001
                    pass
        await asyncio.gather(*[worker() for _ in range(args.warm_concurrency)])
    return sent, ok


def run_warm(args) -> int:
    """独立进程跑一遍预热；父进程在每档开测前调它。"""
    data = json.loads(Path(args.queries).read_text(encoding="utf-8"))
    catalog = Catalog(data, random.Random(args.seed), args.catalog)   # 与测档同一套目录
    headers, _ = _credentials(args)
    rng = random.Random(args.warm_seed)
    t0 = time.perf_counter()
    sent, ok = asyncio.run(_warm_async(args, catalog, headers, date.today(), rng))
    print(f"  预热 {ok}/{sent} 条，用时 {time.perf_counter() - t0:.1f}s", flush=True)
    return 0 if ok else 1


def merge(shards: list[dict], procs: int) -> list[dict]:
    merged = []
    for idx, base in enumerate(shards[0]["phases"]):
        acc = {
            "concurrency": base["concurrency"] * procs,
            "duration_s": max(s["phases"][idx]["duration_s"] for s in shards),
            "requests": 0, "issued": 0, "failed": 0, "degraded": 0, "empty": 0,
            "hang_gt_10s": 0, "sum_ms": 0.0, "max": 0.0, "cpu_cores": 0.0,
            "hist": [0] * H_N,
            "kinds": {k: {"n": 0, "empty": 0, "sum_ms": 0.0, "hist": [0] * H2_N}
                      for k in KINDS},
            "pages": {str(p): {"n": 0, "empty": 0, "sum_ms": 0.0, "hist": [0] * H2_N}
                      for p in range(1, MAX_PAGE + 1)},
            "statuses": Counter(), "errors": Counter(),
            "modes": Counter(), "time_weight": Counter(),
        }
        for s in shards:
            ph = s["phases"][idx]
            for k in ("requests", "issued", "failed", "degraded", "empty", "hang_gt_10s"):
                acc[k] += ph.get(k, 0)
            acc["sum_ms"] += ph.get("mean", 0.0) * ph.get("requests", 0)
            acc["max"] = max(acc["max"], ph.get("max", 0.0))
            acc["cpu_cores"] += ph.get("cpu_cores", 0.0)
            h_sum(acc["hist"], ph["hist"])
            for k, v in ph["statuses"].items():
                acc["statuses"][k] += v
            for k, v in ph["errors"].items():
                acc["errors"][k] += v
            for k, v in ph.get("modes", {}).items():
                acc["modes"][k] += v
            for k, v in ph.get("time_weight", {}).items():
                acc["time_weight"][k] += v
            for kind, src in ph["kinds"].items():
                dst = acc["kinds"].setdefault(
                    kind, {"n": 0, "empty": 0, "sum_ms": 0.0, "hist": [0] * H2_N})
                dst["n"] += src["n"]
                dst["empty"] += src["empty"]
                dst["sum_ms"] += src["sum_ms"]
                h_sum(dst["hist"], src["hist"])
            for page, src in ph["pages"].items():
                dst = acc["pages"].setdefault(
                    page, {"n": 0, "empty": 0, "sum_ms": 0.0, "hist": [0] * H2_N})
                dst["n"] += src["n"]
                dst["empty"] += src["empty"]
                dst["sum_ms"] += src["sum_ms"]
                h_sum(dst["hist"], src["hist"])
        acc["throughput"] = round(acc["requests"] / acc["duration_s"], 2) if acc["duration_s"] else 0.0
        acc["mean"] = round(acc["sum_ms"] / acc["requests"], 1) if acc["requests"] else 0.0
        acc["statuses"] = dict(acc["statuses"])
        acc["errors"] = dict(acc["errors"])
        acc["modes"] = dict(acc["modes"])
        acc["time_weight"] = dict(acc["time_weight"])
        merged.append(acc)
    return merged


def _redis(*cmd: str) -> str:
    """走 docker exec 调 redis-cli；.env 里没有密码就空串。"""
    env = ROOT / ".env"
    password = ""
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("REDIS_PASSWORD"):
                password = line.split("=", 1)[1].strip()
                break
    res = subprocess.run(["docker", "exec", "redis", "redis-cli", "--no-auth-warning",
                          "-a", password, *cmd], capture_output=True, text=True, timeout=120)
    return res.stdout.strip()


# 只删报表缓存，Session / 限流那些键不动
FLUSH_LUA = ("local n=0 for _,k in ipairs(redis.call('keys','oirf:report:*')) "
             "do redis.call('del',k) n=n+1 end return n")


def redis_flush() -> int:
    try:
        return int(_redis("eval", FLUSH_LUA, "0") or 0)
    except Exception:                                              # noqa: BLE001
        return -1


def redis_baseline() -> dict:
    """缓存起点/终点：键数、内存、累计命中与淘汰。"""
    out: dict = {}
    try:
        out["keys"] = int(_redis("dbsize") or 0)
        for line in _redis("info", "memory").splitlines():
            if line.startswith("used_memory:"):
                out["used_mb"] = round(int(line.split(":")[1]) / 1048576, 1)
        for line in _redis("info", "stats").splitlines():
            k, _, v = line.partition(":")
            if k in ("keyspace_hits", "keyspace_misses", "evicted_keys") and v.strip().isdigit():
                out[k] = int(v)
    except Exception:                                              # noqa: BLE001
        pass
    return out


def redis_delta() -> dict | None:
    """读一次 Redis 统计；跑前跑后各读一次，差值就是这套混合查询的真实命中率。"""
    try:
        out = _redis("info", "stats")
    except Exception:                                              # noqa: BLE001
        return None
    vals = {}
    for line in out.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            if v.strip().isdigit():
                vals[k] = int(v)
    return vals or None


def print_redis(before: dict | None, after: dict | None) -> None:
    if not before or not after:
        return
    hits = after.get("keyspace_hits", 0) - before.get("keyspace_hits", 0)
    miss = after.get("keyspace_misses", 0) - before.get("keyspace_misses", 0)
    if hits + miss:
        print(f"\nRedis 命中 {hits} / {hits + miss} = {hits / (hits + miss):.2%}"
              f"（miss {miss}）", flush=True)


def print_breakdown(phases: list[dict]) -> None:
    """按检索形态和页码拆开看：哪种查询慢、哪种查不到东西。"""
    total = {k: 0 for k in KINDS}
    for b in phases:
        for k, v in b["kinds"].items():
            total[k] = total.get(k, 0) + v["n"]
    grand = sum(total.values()) or 1

    print(f"\n{'形态':<9} {'占比':>6} {'p50':>7} {'p95':>7} {'空结果':>7}", flush=True)
    for k in KINDS:
        agg = {"n": 0, "empty": 0, "hist": [0] * H2_N}
        for b in phases:
            src = b["kinds"].get(k)
            if not src:
                continue
            agg["n"] += src["n"]
            agg["empty"] += src["empty"]
            h_sum(agg["hist"], src["hist"])
        if not agg["n"]:
            continue
        print(f"{k:<9} {agg['n'] / grand:>6.1%} {h_pct(agg['hist'], 50, h2_value):>7.0f} "
              f"{h_pct(agg['hist'], 95, h2_value):>7.0f} "
              f"{agg['empty'] / agg['n']:>7.1%}", flush=True)

    pages = {p: {"n": 0, "empty": 0, "sum": 0.0} for p in range(1, MAX_PAGE + 1)}
    for b in phases:
        for p, src in b["pages"].items():
            pages[int(p)]["n"] += src["n"]
            pages[int(p)]["empty"] += src["empty"]
            pages[int(p)]["sum"] += src["sum_ms"]
    print(f"\n{'页码':<4} {'占比':>6} {'均值ms':>8} {'空结果':>7}", flush=True)
    for p in range(1, MAX_PAGE + 1):
        v = pages[p]
        if not v["n"]:
            continue
        print(f"{p:<4} {v['n'] / grand:>6.1%} {v['sum'] / v['n']:>8.1f} "
              f"{v['empty'] / v['n']:>7.1%}", flush=True)


def _wait_all_done(d: Path, idx: int, procs: int, children: list,
                   timeout: float) -> None:
    """父进程等 8 个分片都把这一档跑完（各自放下 done{idx}-{i}）。"""
    deadline = time.time() + timeout
    need = [d / f"done{idx}-{i:02d}" for i in range(procs)]
    while True:
        if all(p.exists() for p in need):
            return
        for i, _shard_out, proc in children:
            if proc.poll() is not None and not need[i].exists():
                raise SystemExit(f"分片 {i} 在档 {idx} 提前退出（退出码 {proc.returncode}）")
        if time.time() > deadline:
            raise SystemExit(f"等档 {idx} 跑完超时（{timeout:.0f}s）")
        time.sleep(0.5)


def reset_and_warm(args, env: dict) -> dict:
    """清空报表缓存 → 按固定种子预热 → 返回基线（键数/内存/累计计数）。"""
    flushed = redis_flush()
    if flushed < 0:
        raise SystemExit("清缓存失败：docker exec redis 不通，检查容器名或 .env 里的 REDIS_PASSWORD")
    cmd = [sys.executable, "-u", str(Path(__file__).resolve()),
           "--warm-only", "--warm-requests", str(args.warm_requests),
           "--warm-seed", str(args.warm_seed),
           "--warm-concurrency", str(args.warm_concurrency),
           "--base-url", args.base_url, "--catalog", str(args.catalog),
           "--seed", str(args.seed), "--queries", str(args.queries),
           "--timeout", str(args.timeout)]
    subprocess.run(cmd, cwd=ROOT, env=env, check=False)
    base = redis_baseline()
    base["flushed"] = flushed
    if not base.get("keys"):
        raise SystemExit("预热后缓存还是空的：api 没起、或登录失败，看一下上面的预热输出")
    return base


def run_parent(args) -> int:
    procs = args.procs
    out = Path(args.out)
    shard_dir = out.parent / f"{out.stem}-shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    for f in list(shard_dir.glob("go[0-9]*")) + list(shard_dir.glob("done[0-9]*")):
        f.unlink()
    headers, user_id = login(args.base_url, args.username, args.password)
    levels = [int(x) for x in args.levels.split(",") if x.strip()]
    gated = args.reset_cache != "none"

    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONPATH=str(ROOT),
               RAMP_TOKEN=headers["Authorization"].split(" ", 1)[1],
               RAMP_USER_ID=str(user_id))
    children = []
    print(f"\n=== {procs} 个进程，每档 ×{procs}；词库 {args.queries} ===", flush=True)
    print(f"=== 缓存协议：{'清空 + 预热 ' + str(args.warm_requests) + ' 条' if gated else '不重置'} ===\n",
          flush=True)
    for i in range(procs):
        shard_out = shard_dir / f"shard{i:02d}.json"
        cmd = [sys.executable, "-u", str(Path(__file__).resolve()),
               "--base-url", args.base_url, "--levels", args.levels,
               "--duration", str(args.duration), "--timeout", str(args.timeout),
               "--catalog", str(args.catalog), "--seed", str(args.seed),
               "--queries", str(args.queries), "--procs", "1", "--reset-cache", "none",
               "--tag", args.tag, "--shard", f"{i}/{procs}", "--out", str(shard_out)]
        if gated:
            cmd += ["--barrier-dir", str(shard_dir)]
        children.append((i, shard_out, subprocess.Popen(cmd, cwd=ROOT, env=env)))

    print(f"{'总并发':>6} {'时长':>6} {'请求':>8} {'吞吐':>8} {'p50':>7} {'p95':>7} "
          f"{'p99':>7} {'空结果':>7} {'错误':>5} {'降级':>5} {'客户端核':>8}", flush=True)
    baselines: list[dict] = []
    for idx, conc in enumerate(levels):
        if gated:
            base = reset_and_warm(args, env)
            baselines.append(base)
            print(f"  [档 {conc}] 清掉 {base.get('flushed')} 键 → 基线 {base.get('keys')} 键 / "
                  f"{base.get('used_mb')} MB", flush=True)
        (shard_dir / f"go{idx}").touch()
        try:
            _wait_all_done(shard_dir, idx, procs, children,
                           timeout=args.duration + args.timeout + 300)
        except SystemExit:
            for _, _, p in children:          # 一档崩了就把其余分片一起收掉
                if p.poll() is None:
                    p.terminate()
            raise
        if gated:
            after = redis_baseline()
            b = baselines[idx]
            hits = after.get("keyspace_hits", 0) - b.get("keyspace_hits", 0)
            miss = after.get("keyspace_misses", 0) - b.get("keyspace_misses", 0)
            b["hits"], b["misses"], b["keys_end"] = hits, miss, after.get("keys")
            b["evicted"] = after.get("evicted_keys", 0) - b.get("evicted_keys", 0)
            rate = f"{hits / (hits + miss):.2%}" if hits + miss else "n/a"
            print(f"  [档 {conc}] 命中 {hits}/{hits + miss} = {rate}，"
                  f"淘汰 {b['evicted']}，缓存 {after.get('keys')} 键", flush=True)

    results = []
    for i, shard_out, proc in children:
        code = proc.wait()
        if code != 0 or not shard_out.exists():
            print(f"  分片 {i} 失败（退出码 {code}）", flush=True)
            for _, _, p in children:
                if p.poll() is None:
                    p.terminate()
            return 1
        results.append(json.loads(shard_out.read_text(encoding="utf-8")))

    merged = merge(results, procs)
    for b in merged:
        print(f"{b['concurrency']:>6} {b['duration_s']:>6.0f} {b['requests']:>8} "
              f"{b['throughput']:>8.1f} {h_pct(b['hist'], 50):>7.0f} "
              f"{h_pct(b['hist'], 95):>7.0f} {h_pct(b['hist'], 99):>7.0f} "
              f"{b['empty'] / max(b['requests'], 1):>7.1%} {b['failed']:>5} "
              f"{b['degraded']:>5} {b['cpu_cores']:>8.2f}", flush=True)

    print_breakdown(merged)

    out.write_text(json.dumps({"tag": args.tag, "seed": args.seed, "procs": procs,
                               "warm_requests": args.warm_requests if gated else 0,
                               "warm_seed": args.warm_seed if gated else None,
                               "baselines": baselines, "phases": merged},
                              ensure_ascii=False), encoding="utf-8")
    print(f"\n结果已写入 {out}", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--username", default="stress1")
    ap.add_argument("--password", default="stresspass123")
    ap.add_argument("--levels", default="64", help="逗号分隔的每进程并发")
    ap.add_argument("--duration", type=float, default=60.0, help="每档秒数")
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--procs", type=int, default=1, help="进程数，总并发 = 档位 × procs")
    ap.add_argument("--catalog", type=int, default=2000, help="查询目录条数")
    ap.add_argument("--seed", type=int, default=20261019)
    ap.add_argument("--queries", default=str(QUERIES))
    ap.add_argument("--tag", default="mix")
    ap.add_argument("--out", default=str(ROOT / "stress" / "archive" / "run" / "mix.json"))
    ap.add_argument("--shard", default="", help="内部使用：i/N")
    ap.add_argument("--reset-cache", default="flush+warm", choices=("flush+warm", "none"),
                    help="每档开测前把缓存恢复成同一个基线（默认清空+预热）；none 就不管缓存")
    ap.add_argument("--warm-requests", type=int, default=4000, help="基线预热条数")
    ap.add_argument("--warm-seed", type=int, default=777, help="预热用的随机种子（固定才可复现）")
    ap.add_argument("--warm-concurrency", type=int, default=64, help="预热并发")
    ap.add_argument("--warm-only", action="store_true", help="内部使用：只跑预热")
    ap.add_argument("--barrier-dir", default="", help="内部使用：父进程用 go/done 文件对齐档位")
    args = ap.parse_args()

    if not Path(args.queries).exists():
        print(f"缺词库 {args.queries}，先跑 python stress/build_queries.py", flush=True)
        return 2
    if args.warm_only:
        return run_warm(args)
    if args.shard:                        # 分片；缓存由父进程负责
        return run_shard(args)
    if args.procs == 1 and args.reset_cache != "none":   # 单进程：开跑前做一次基线
        base = reset_and_warm(args, dict(os.environ))
        print(f"缓存基线：{base.get('keys')} 键 / {base.get('used_mb')} MB", flush=True)
    before = None if args.reset_cache != "none" else redis_delta()
    rc = run_parent(args) if args.procs > 1 else run_shard(args)
    if before:
        print_redis(before, redis_delta())
    return rc


if __name__ == "__main__":
    sys.exit(main())
