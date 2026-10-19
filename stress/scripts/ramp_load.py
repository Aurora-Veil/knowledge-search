"""阶梯加压器：按"时长档位"逐级提升并发，直到服务失效或容器崩溃。

与 stress/stress_search.py 的区别（它按固定请求数跑固定档位）：
    1. 每档跑**固定时长**，样本量随吞吐自适应，避免"200 请求/档"在小吞吐下的噪声
    2. 一次进程内走完整条阶梯，档与档之间不断连接，省掉重建开销
    3. 到档中止条件立即停，并记录**中止时的现场**（错误分类、降级计数、时序）
    4. 逐秒时序，用来把客户端曲线和容器指标对齐
    5. **多进程分片**（--procs）：单进程 httpx 有硬顶，见下

用法（仓库根目录）：
    $env:PYTHONIOENCODING='utf-8'; $env:PYTHONPATH=(Get-Location).Path
    # 默认阶梯，自动中止
    python stress/scripts/ramp_load.py --tag p1 --out stress/run/p1.json
    # 指定阶梯
    python stress/scripts/ramp_load.py --levels 8,16,32,64,96,128 --duration 45
    # 细档逼近
    python stress/scripts/ramp_load.py --levels 120,140,160,180 --duration 60 --tag p2
    # 8 个进程，每档 192×8 = 1536 个并发
    python stress/scripts/ramp_load.py --levels 192 --procs 8 --duration 120 --tag p8

中止条件（任一命中即停该轮并记录，--no-abort 可关掉以便看完全程）：
    err_rate > --max-err-rate（默认 0.05）           服务已经废了
    p95 > --max-p95-ms（默认 15000）                 事实性挂起
    吞吐连续两档下降 > --drop-ratio（默认 0.20）       进入 thrashing

"降级"单列：编码服务不可用时接口仍返 200 但 `degraded=true`，只看状态码会漏掉这种崩溃。

--- 为什么需要 --procs ---

单进程 httpx 客户端测不出这台服务的真实上限。实测（stress/why60.py）：

    c=64  async 87.8 req/s（客户端只用 0.27 核）  |  线程版 128.0 req/s
    c=192 async 51~60 req/s                      |  线程版 106.4 req/s

async 版的网络耗时和服务端响应时间与线程版几乎一样，但**同时在飞的请求数远低于名义并发**
（c=64 时实际只有约 41 个）。原因在 httpcore/_async/connection_pool.py 的
`_assign_requests_to_connections()`：每有一个请求进出连接池就重扫整个队列×连接列表，
而且第 294 行把 `len([c.is_idle() for c in self._connections])` 写在连接循环体内，
单个请求的进出就要做 O(n²) 次操作，全部串在唯一的事件循环上。**并发越高，客户端越在
自己内部空转**——所以并发从 64 加到 1536，吞吐一直是六十几，而服务端 CPU 反而从 333%
掉到 102%、ES rejected 恒为 0、PG 无锁等待。压力根本没送上去。

--procs 用多进程绕开这个 O(n²)：每个子进程有自己的事件循环和连接池，吞吐近似相加。
父进程把各分片的延迟直方图、状态码、错误、逐秒桶合并成一份与单进程版**同结构**的 JSON，
所以 stress/analyze.py 等消费方不用改。
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # stress/scripts/ramp_load.py → 仓库根目录
sys.path.insert(0, str(ROOT))

import httpx                                                          # noqa: E402

TOPICS = [
    "人工智能", "大模型", "新能源汽车", "储能", "半导体", "机器人", "医疗健康",
    "光伏", "碳中和", "数字经济", "智能制造", "生物医药", "芯片", "低空经济",
    "氢能", "锂电", "工业互联网", "元宇宙", "出海", "消费",
]

DEFAULT_LEVELS = [8, 12, 16, 24, 32, 48, 64, 80, 96, 128, 160, 192, 256, 384, 512]

# 高危调用：容器内 ES / 应用侧都可能出现的错误关键字，用于把异常归类
NET_ERRORS = ("ConnectError", "ConnectTimeout", "ReadTimeout", "ReadError",
              "RemoteProtocolError", "PoolTimeout", "WriteError", "WriteTimeout",
              "ConnectionResetError", "ServerDisconnectedError", "LocalProtocolError")


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))]


# 延迟直方图：1 ms 一桶到 10 s，之后 10 ms 一桶到 60 s，再往上单独一桶。
# 分片合并时不能把各进程的 p95 平均（百分位不可加），必须合原始分布；直方图
# 比存原始样本小两个数量级，p95 误差 ≤ 10 ms，对找崩溃点足够。
HIST_FINE_MAX_MS = 10_000
HIST_MID_MAX_MS = 60_000
HIST_BUCKETS = HIST_FINE_MAX_MS + (HIST_MID_MAX_MS - HIST_FINE_MAX_MS) // 10 + 1


def hist_index(ms: float) -> int:
    if ms < HIST_FINE_MAX_MS:
        return max(0, int(ms))
    if ms < HIST_MID_MAX_MS:
        return HIST_FINE_MAX_MS + int((ms - HIST_FINE_MAX_MS) / 10)
    return HIST_BUCKETS - 1


def hist_value(index: int) -> float:
    if index < HIST_FINE_MAX_MS:
        return float(index)
    if index < HIST_BUCKETS - 1:
        return HIST_FINE_MAX_MS + (index - HIST_FINE_MAX_MS) * 10.0
    return float(HIST_MID_MAX_MS)


def histogram(values: list[float]) -> list[int]:
    counts = [0] * HIST_BUCKETS
    for value in values:
        counts[hist_index(value)] += 1
    return counts


def hist_pct(counts: list[int], p: float) -> float:
    total = sum(counts)
    if not total:
        return 0.0
    target = p / 100 * (total - 1)
    seen = 0
    for index, count in enumerate(counts):
        if count and seen + count > target:
            return hist_value(index)
        seen += count
    return hist_value(HIST_BUCKETS - 1)


def hist_max(counts: list[int]) -> float:
    for index in range(len(counts) - 1, -1, -1):
        if counts[index]:
            return hist_value(index)
    return 0.0


class CpuSampler:
    """后台线程按间隔采样本进程 CPU，用来判断客户端自己吃了几个核。

    这条数据是分片数的决策依据：客户端把 16 个线程吃满之后，再加分片只会
    让客户端和服务端互相抢 CPU，吞吐反而会掉。没有 psutil，Windows 走
    GetProcessTimes，Linux 走 /proc/self/stat。
    """

    def __init__(self, interval: float = 0.25) -> None:
        self.interval = interval
        self.samples: list[tuple[float, float]] = []   # (核数, 该样本跨越的秒数)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> CpuSampler:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def _loop(self) -> None:
        try:
            prev_t, prev_cpu = time.perf_counter(), process_cpu_seconds()
        except Exception:                                          # noqa: BLE001
            return
        while not self._stop.wait(self.interval):
            try:
                now, cpu = time.perf_counter(), process_cpu_seconds()
            except Exception:                                      # noqa: BLE001
                return
            dt = now - prev_t
            if dt > 0:
                self.samples.append(((cpu - prev_cpu) / dt, dt))
            prev_t, prev_cpu = now, cpu

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def cores(self) -> float:
        if not self.samples:
            return 0.0
        span = sum(dt for _, dt in self.samples)
        return sum(c * dt for c, dt in self.samples) / span if span else 0.0


def process_cpu_seconds() -> float:
    """本进程累计 CPU 秒数（含所有线程）。"""
    if sys.platform == "win32":
        import ctypes
        import ctypes.wintypes as wt

        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", wt.DWORD),
                        ("dwHighDateTime", wt.DWORD)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wt.HANDLE
        k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
        k32.GetProcessTimes.argtypes = [wt.HANDLE,
                                        ctypes.POINTER(FILETIME),
                                        ctypes.POINTER(FILETIME),
                                        ctypes.POINTER(FILETIME),
                                        ctypes.POINTER(FILETIME)]
        k32.CloseHandle.argtypes = [wt.HANDLE]
        handle = k32.OpenProcess(0x0400 | 0x0010, False, os.getpid())
        if not handle:
            return 0.0
        try:
            c, e, k, u = FILETIME(), FILETIME(), FILETIME(), FILETIME()
            if not k32.GetProcessTimes(handle, ctypes.byref(c), ctypes.byref(e),
                                       ctypes.byref(k), ctypes.byref(u)):
                return 0.0
            ticks = ((k.dwHighDateTime << 32) | k.dwLowDateTime) + \
                    ((u.dwHighDateTime << 32) | u.dwLowDateTime)
            return ticks / 1e7
        finally:
            k32.CloseHandle(handle)
    with open("/proc/self/stat", "rb") as fh:
        fields = fh.read().rsplit(b")", 1)[1].split()
    hz = os.sysconf("SC_CLK_TCK")
    return (int(fields[11]) + int(fields[12])) / hz


class Bucket:
    """1 秒时间桶，用于客户端侧时序。"""

    __slots__ = ("second", "n", "errors", "degraded", "lat_sum", "lat_max", "hang")

    def __init__(self, second: int) -> None:
        self.second = second
        self.n = 0
        self.errors = 0
        self.degraded = 0
        self.lat_sum = 0.0
        self.lat_max = 0.0
        self.hang = 0

    def as_dict(self) -> dict:
        return {"t": self.second, "n": self.n, "errors": self.errors,
                "degraded": self.degraded,
                "mean_ms": round(self.lat_sum / self.n, 1) if self.n else None,
                "max_ms": round(self.lat_max, 1), "hang": self.hang}


def _phase_duration(args, concurrency: int) -> float:
    """auto 模式：秒数 = 并发 × 系数，夹在 [dur_min, dur_max] 内。

    固定秒数会让高并发档的请求数远低于低并发档（吞吐饱和后请求量与时长的关系断掉），
    auto 让每档请求量落在同一量级，档间比较才有意义。
    """
    if str(args.duration).lower() == "auto":
        return min(args.dur_max, max(args.dur_min, concurrency * args.dur_factor))
    return float(args.duration)


class Phase:
    def __init__(self, concurrency: int, duration: float) -> None:
        self.concurrency = concurrency
        self.duration = duration
        self.latencies: list[float] = []
        self.statuses: Counter = Counter()
        self.errors: Counter = Counter()
        self.degraded = 0
        self.hang = 0
        self.samples: list[str] = []
        self.buckets: dict[int, Bucket] = {}
        self.issued = 0
        self.wall = 0.0
        self.cpu_cores = 0.0
        self.aborted: str | None = None
        self.deadline: float = 0.0

    def add(self, latency: float, status: int, err: str | None,
            degraded: bool, second: int) -> None:
        bucket = self.buckets.get(second)
        if bucket is None:
            bucket = self.buckets[second] = Bucket(second)
        bucket.n += 1
        bucket.lat_sum += latency
        bucket.lat_max = max(bucket.lat_max, latency)
        self.latencies.append(latency)
        self.statuses[status] += 1
        if latency > 10_000:
            self.hang += 1
            bucket.hang += 1
        if err:
            self.errors[err] += 1
            bucket.errors += 1
        if degraded:
            self.degraded += 1
            bucket.degraded += 1

    def summary(self) -> dict:
        n = len(self.latencies)
        failed = sum(v for k, v in self.statuses.items() if k != 200) + sum(self.errors.values())
        return {
            "concurrency": self.concurrency,
            "duration_s": round(self.wall, 2),
            "requests": n,
            "issued": self.issued,
            "in_flight_at_stop": self.issued - n,
            "throughput": round(n / self.wall, 2) if self.wall else 0.0,
            "statuses": {str(k): v for k, v in sorted(self.statuses.items())},
            "errors": dict(self.errors),
            "degraded": self.degraded,
            "hang_gt_10s": self.hang,
            "p50": round(pct(self.latencies, 50), 1),
            "p90": round(pct(self.latencies, 90), 1),
            "p95": round(pct(self.latencies, 95), 1),
            "p99": round(pct(self.latencies, 99), 1),
            "max": round(max(self.latencies), 1) if self.latencies else 0.0,
            "mean": round(statistics.fmean(self.latencies), 1) if self.latencies else 0.0,
            "error_rate": round(failed / n, 4) if n else 0.0,
            "failed": failed,
            "cpu_cores": round(self.cpu_cores, 3),
            "aborted": self.aborted,
            "samples": self.samples[:6],
            "buckets": [b.as_dict() for b in sorted(self.buckets.values(), key=lambda x: x.second)],
            # 给多进程合并用：自描述，绝不传索引位置
            "histogram": {"fine_max_ms": HIST_FINE_MAX_MS,
                          "mid_max_ms": HIST_MID_MAX_MS,
                          "widths_ms": [1, 10],
                          "counts": histogram(self.latencies)},
        }


async def drive_phase(client: httpx.AsyncClient, phase: Phase, args,
                      headers: dict, topics: list[str], start_index: int,
                      stop: asyncio.Event) -> None:
    """按并发上限持续打 phase.duration 秒；每 0.5 s 检查一次中止条件。"""
    sem = asyncio.Semaphore(phase.concurrency)
    counter = {"i": start_index}
    lock = asyncio.Lock()
    t0 = time.perf_counter()
    deadline = t0 + phase.duration
    last_check = t0

    async def one() -> None:
        async with sem:
            if stop.is_set():
                return
            async with lock:
                index = counter["i"]
                counter["i"] += 1
            body = {"q": topics[index % len(topics)], "size": 20}
            started = time.perf_counter()
            status = 0
            err: str | None = None
            degraded = False
            text = ""
            try:
                res = await client.post("/api/v1/reports/search", json=body, headers=headers)
                status = res.status_code
                text = res.text[:200]
                if status == 200:
                    try:
                        degraded = bool(res.json().get("degraded"))
                    except Exception:                                   # noqa: BLE001
                        degraded = True
            except Exception as exc:                                    # noqa: BLE001
                name = type(exc).__name__
                err = name if name in NET_ERRORS else f"other:{name}"
                text = f"{name}: {exc}"[:200]
            latency = (time.perf_counter() - started) * 1000
            phase.issued += 1
            second = int(time.perf_counter() - t0)
            phase.add(latency, status, err, degraded, second)
            if status != 200 and len(phase.samples) < 6:
                phase.samples.append(f"{status} {text}")

    async def worker() -> None:
        # 每个协程在时限内不断取活，保证并发数恒定，不受单请求时长影响
        while time.perf_counter() < deadline and not stop.is_set():
            await one()

    tasks = [asyncio.create_task(worker()) for _ in range(phase.concurrency)]
    try:
        while time.perf_counter() < deadline and not stop.is_set():
            await asyncio.sleep(0.5)
            now = time.perf_counter()
            if now - last_check < 0.5:
                continue
            last_check = now
            if phase.deadline and now > phase.deadline:
                phase.aborted = f"墙钟上限 {args.max_wall:.0f}s 到，仍有请求在飞"
                stop.set()
                break
            if args.no_abort:
                continue
            s = _provisional(phase)
            if s["error_rate"] > args.max_err_rate:
                phase.aborted = f"错误率 {s['error_rate']:.1%} > {args.max_err_rate:.0%}"
                stop.set()
            elif s["p95"] > args.max_p95_ms:
                phase.aborted = f"p95 {s['p95']:.0f} ms > {args.max_p95_ms:.0f} ms"
                stop.set()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        phase.wall = time.perf_counter() - t0


def _provisional(phase: Phase) -> dict:
    n = len(phase.latencies)
    failed = sum(v for k, v in phase.statuses.items() if k != 200) + sum(phase.errors.values())
    return {"error_rate": failed / n if n else 0.0, "p95": pct(phase.latencies, 95)}


async def warmup(client: httpx.AsyncClient, headers: dict, count: int) -> None:
    for i in range(count):
        try:
            await client.post("/api/v1/reports/search",
                              json={"q": TOPICS[i % len(TOPICS)], "size": 20},
                              headers=headers)
        except Exception:                                               # noqa: BLE001
            pass


def login(base_url: str, username: str, password: str,
          quiet: bool = False) -> tuple[dict, int]:
    with httpx.Client(base_url=base_url, timeout=30) as client:
        res = client.post("/api/v1/auth/register",
                          json={"username": username, "password": password})
        if not quiet:
            print(f"注册 {username}: {res.status_code}"
                  f"{'（已存在）' if res.status_code == 409 else ''}")
        res = client.post("/api/v1/auth/token",
                          data={"username": username, "password": password})
        res.raise_for_status()
        headers = {"Authorization": f"Bearer {res.json()['access_token']}"}
        me = client.get("/api/v1/auth/me", headers=headers).json()
        return headers, me["id"]


def _credentials(args) -> tuple[dict, int]:
    """取本次要用的 Authorization 头与 user_id。

    多进程模式下父进程已经登录过一次，token 由 RAMP_TOKEN 环境变量传进来，
    分片不再各自认证。分片各自登录会在开跑前叠一层认证风暴，而认证与检索
    抢的是同一个线程池额度：先登录完的分片立刻开打，晚登录的分片排在队尾，
    超过 login() 的 30 秒超时后整片退出，该档实际并发低于名义值。
    """
    token = os.environ.get("RAMP_TOKEN")
    if token:
        return {"Authorization": f"Bearer {token}"}, int(os.environ.get("RAMP_USER_ID") or 0)
    return login(args.base_url, args.username, args.password, quiet=bool(args.shard))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", default="stress1")
    parser.add_argument("--password", default="stresspass123")
    parser.add_argument("--levels", default="", help="逗号分隔的并发档位（每个进程各跑一份）")
    parser.add_argument("--duration", default="auto",
                        help="每档秒数；auto = 并发×系数（见 --dur-factor），保证各档请求量同量级")
    parser.add_argument("--dur-factor", type=float, default=4.0,
                        help="auto 模式：秒数 = 并发 × 该系数")
    parser.add_argument("--dur-min", type=float, default=30.0, help="auto 模式下限秒")
    parser.add_argument("--dur-max", type=float, default=240.0, help="auto 模式上限秒")
    parser.add_argument("--max-wall", type=float, default=600.0,
                        help="单档墙钟硬上限秒；高并发下避免长尾挂起拖住整轮")
    parser.add_argument("--timeout", type=float, default=90.0, help="单请求超时秒")
    parser.add_argument("--warmup", type=int, default=30, help="每档前热身请求数（只有 0 号分片做）")
    parser.add_argument("--max-err-rate", type=float, default=0.05)
    parser.add_argument("--max-p95-ms", type=float, default=15000.0)
    parser.add_argument("--drop-ratio", type=float, default=0.20)
    parser.add_argument("--no-abort", action="store_true", help="不自动中止，跑完所有档")
    parser.add_argument("--tag", default="ramp")
    parser.add_argument("--out", required=True)
    parser.add_argument("--procs", type=int, default=1,
                        help="压测进程数。总并发 = 档位 × procs；单进程 httpx 有 ~60 req/s 硬顶，"
                             "要压出真实上限必须 >1")
    parser.add_argument("--shards-dir", default="", help="分片中间产物目录（默认与 --out 同级的 "
                                                         "<stem>-shards/）")
    parser.add_argument("--keep-shards", action="store_true", help="保留分片 JSON 便于排查")
    parser.add_argument("--shard", default="", help="内部使用：本进程的分片号，形如 2/8")
    return parser


def _parse_levels(args) -> list[int]:
    return ([int(x) for x in args.levels.split(",") if x.strip()]
            if args.levels else list(DEFAULT_LEVELS))


def run_single(args) -> int:
    """一个压测进程跑完整条阶梯，把结果写进 --out。"""
    levels = _parse_levels(args)
    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    shard_idx, shard_total = 0, 1
    if args.shard:
        left, _, right = args.shard.partition("/")
        shard_idx, shard_total = int(left), int(right or 1)
    label = f"[{shard_idx}/{shard_total}] " if shard_total > 1 else ""

    headers, user_id = _credentials(args)
    # 只有 0 号分片热身：8 个进程各热 30 次会先在服务上堆一波无用负载
    warmup_count = args.warmup if shard_idx == 0 else 0

    limits = httpx.Limits(max_connections=max(levels) + 8,
                          max_keepalive_connections=max(levels) + 8)
    phases: list[dict] = []
    aborted_at: str | None = None
    stop_all = asyncio.Event()
    index = 0

    print(f"\n{label}阶梯 {levels}  每档 {args.duration}s  用户 id={user_id}  run={run_id}\n",
          flush=True)
    print(f"{label}{'并发':>5} {'时长':>6} {'请求':>7} {'吞吐':>8} {'p50':>7} {'p95':>7} "
          f"{'p99':>7} {'降级':>5} {'挂起':>5} {'错误':>6} {'核':>5}  状态/异常", flush=True)

    async def run_all() -> None:
        nonlocal index
        async with httpx.AsyncClient(base_url=args.base_url, timeout=args.timeout,
                                     limits=limits) as client:
            for n, concurrency in enumerate(levels, 1):
                if stop_all.is_set():
                    break
                if warmup_count:
                    await warmup(client, headers, warmup_count)
                duration = _phase_duration(args, concurrency)
                phase = Phase(concurrency, duration)
                phase.deadline = time.perf_counter() + duration + args.max_wall
                sampler = CpuSampler().start()
                try:
                    await drive_phase(client, phase, args, headers, TOPICS, index,
                                      stop_all)
                finally:
                    sampler.stop()
                    phase.cpu_cores = sampler.cores()
                index += phase.issued
                block = phase.summary()
                phases.append(block)
                status_txt = " ".join(f"{k}×{v}" for k, v in block["statuses"].items())
                err_txt = " ".join(f"{k}×{v}" for k, v in block["errors"].items())
                print(f"{label}{concurrency:>5} {block['duration_s']:>6.0f} "
                      f"{block['requests']:>7} "
                      f"{block['throughput']:>8.1f} {block['p50']:>7.0f} {block['p95']:>7.0f} "
                      f"{block['p99']:>7.0f} {block['degraded']:>5} {block['hang_gt_10s']:>5} "
                      f"{block['failed']:>6} {block['cpu_cores']:>5.2f}  {status_txt} {err_txt}",
                      flush=True)
                for line in block["samples"][:2]:
                    print(f"        {label}例：{line}", flush=True)

                # 吞吐连续两档下降 → thrashing。--no-abort 时只记录不中止：
                # 找崩溃点必须跑完所有档，否则永远看不到后面还在不在掉。
                # 分片里不判：子进程只看得到自己那 1/procs 的吞吐，判了会误伤。
                if shard_total == 1 and len(phases) >= 3:
                    prev, prev2 = phases[-2]["throughput"], phases[-3]["throughput"]
                    if prev > 0 and prev2 > 0 and block["throughput"] < prev * (1 - args.drop_ratio) \
                            and prev < prev2 * (1 - args.drop_ratio):
                        phase.aborted = (f"吞吐连续两档下降：{prev2:.1f} → {prev:.1f} → "
                                         f"{block['throughput']:.1f} req/s")
                        stop_all.set()
                if phase.aborted and not args.no_abort:
                    aborted_at = f"并发 {concurrency}：{phase.aborted}"
                    print(f"\n!! {label}中止于并发 {concurrency}：{phase.aborted}", flush=True)
                    break
                if phase.aborted:
                    print(f"\n!! {label}并发 {concurrency} 触发判据（--no-abort，继续加压）："
                          f"{phase.aborted}", flush=True)
                    phase.aborted = None

    try:
        asyncio.run(run_all())
    except KeyboardInterrupt:
        aborted_at = "人工中断"
    except Exception as exc:                                            # noqa: BLE001
        aborted_at = f"客户端异常退出：{type(exc).__name__}: {exc}"
        print(f"\n!! {label}{aborted_at}", flush=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"run_id": run_id, "tag": args.tag, "user_id": user_id,
               "shard": args.shard or "0/1",
               "config": {"levels": levels, "duration": args.duration,
                          "timeout": args.timeout, "warmup": args.warmup,
                          "max_err_rate": args.max_err_rate,
                          "max_p95_ms": args.max_p95_ms,
                          "no_abort": args.no_abort},
               "aborted_at": aborted_at, "phases": phases}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{label}结果已写入 {out}", flush=True)
    print(f"{label}共 {len(phases)} 档，中止点：{aborted_at or '未触发'}", flush=True)
    return 0 if phases else 2


def _as_int_map(values) -> dict[int, int]:
    return {int(k): int(v) for k, v in (values or {}).items()}


def aggregate(shard_runs: list[dict], procs: int, args) -> dict:
    """把各分片合并成一份与单进程版同结构的 payload。

    每个分片独立驱动同一批档位，因此 total_concurrency = 档位 × 分片数。
    延迟合并的是**直方图**而不是各分片的 p95——百分位不可加，平均 p95 是错的。
    """
    base = shard_runs[0]
    levels = [p["concurrency"] for p in base["phases"]]
    per_level: dict[int, list[dict]] = {n: [] for n in levels}
    for run in shard_runs:
        for block in run["phases"]:
            per_level.setdefault(block["concurrency"], []).append(block)

    merged: list[dict] = []
    for level in levels:
        blocks = per_level.get(level) or []
        if not blocks:
            continue
        counts: list[int] = []
        total_requests = total_issued = 0
        total_degraded = total_hang = 0
        total_cpu = 0.0
        statuses: Counter = Counter()
        errors: Counter = Counter()
        walls: list[float] = []
        issued: list[int] = []
        samples: list[str] = []
        aborted_notes: list[str] = []
        bucket_acc: dict[int, dict] = {}
        for block in blocks:
            counts = _merge_histograms(counts, (block.get("histogram") or {}).get("counts") or [])
            total_requests += block.get("requests") or 0
            total_issued += block.get("issued") or 0
            total_degraded += block.get("degraded") or 0
            total_hang += block.get("hang_gt_10s") or 0
            total_cpu += block.get("cpu_cores") or 0.0
            for k, v in _as_int_map(block.get("statuses")).items():
                statuses[k] += v
            for k, v in (block.get("errors") or {}).items():
                errors[k] += v
            walls.append(block.get("duration_s") or 0.0)
            issued.append(block.get("in_flight_at_stop") or 0)
            for line in block.get("samples") or []:
                if len(samples) < 6:
                    samples.append(line)
            if block.get("aborted"):
                aborted_notes.append(str(block["aborted"]))
            for bucket in block.get("buckets") or []:
                acc = bucket_acc.setdefault(bucket["t"], {"t": bucket["t"], "n": 0,
                                                          "errors": 0, "degraded": 0,
                                                          "lat_sum": 0.0, "lat_max": 0.0,
                                                          "hang": 0})
                acc["n"] += bucket["n"]
                acc["errors"] += bucket["errors"]
                acc["degraded"] += bucket["degraded"]
                acc["lat_sum"] += (bucket["mean_ms"] or 0.0) * bucket["n"]
                acc["lat_max"] = max(acc["lat_max"], bucket["max_ms"] or 0.0)
                acc["hang"] += bucket["hang"]

        failed = sum(v for k, v in statuses.items() if k != 200) + sum(errors.values())
        wall = statistics.fmean(walls) if walls else 0.0
        buckets = []
        for acc in sorted(bucket_acc.values(), key=lambda x: x["t"]):
            buckets.append({"t": acc["t"], "n": acc["n"], "errors": acc["errors"],
                            "degraded": acc["degraded"],
                            "mean_ms": round(acc["lat_sum"] / acc["n"], 1) if acc["n"] else None,
                            "max_ms": round(acc["lat_max"], 1), "hang": acc["hang"]})

        merged.append({
            "concurrency": level,
            "total_concurrency": level * procs,
            "procs": procs,
            "duration_s": round(wall, 2),
            "requests": total_requests,
            "issued": total_issued,
            "in_flight_at_stop": sum(issued),
            "throughput": round(total_requests / wall, 2) if wall else 0.0,
            "statuses": {str(k): v for k, v in sorted(statuses.items())},
            "errors": dict(errors),
            "degraded": total_degraded,
            "hang_gt_10s": total_hang,
            # 直方图合并后重算，不是各分片的平均
            "p50": round(hist_pct(counts, 50), 1),
            "p90": round(hist_pct(counts, 90), 1),
            "p95": round(hist_pct(counts, 95), 1),
            "p99": round(hist_pct(counts, 99), 1),
            "max": round(hist_max(counts), 1),
            "mean": round(_hist_mean(counts, total_requests), 1) if total_requests else 0.0,
            "error_rate": round(failed / total_requests, 4) if total_requests else 0.0,
            "failed": failed,
            # 各分片自己的 CPU 相加：客户端总共吃掉几个核（100% = 1 核）
            "cpu_cores": round(total_cpu, 3),
            "aborted": "；".join(dict.fromkeys(aborted_notes)) or None,
            "samples": samples,
            "buckets": buckets,
            "histogram": {"fine_max_ms": HIST_FINE_MAX_MS, "mid_max_ms": HIST_MID_MAX_MS,
                          "widths_ms": [1, 10], "counts": counts},
        })

    return {"run_id": base["run_id"], "tag": args.tag,
            "user_id": base.get("user_id"),
            "procs": procs,
            "shards": [r.get("shard") for r in shard_runs],
            "config": dict(base.get("config") or {}, procs=procs,
                           base_url=args.base_url),
            "aborted_at": "；".join(dict.fromkeys(
                r["aborted_at"] for r in shard_runs if r.get("aborted_at"))) or None,
            "phases": merged}


def _merge_histograms(left: list[int], right: list[int]) -> list[int]:
    if not left:
        return list(right)
    if not right:
        return left
    if len(left) != len(right):
        raise ValueError(f"直方图长度不一致：{len(left)} vs {len(right)}，"
                         "分片之间用了不同的 ramp_load.py 版本？")
    return [a + b for a, b in zip(left, right)]


def _hist_mean(counts: list[int], total: int) -> float:
    if not total:
        return 0.0
    acc = 0.0
    for index, count in enumerate(counts):
        if count:
            acc += hist_value(index) * count
    return acc / total


def run_multi(args) -> int:
    """父进程：拉起 --procs 个子进程，各自跑完整阶梯，然后合并。"""
    procs = max(1, args.procs)
    out = Path(args.out)
    shard_dir = (Path(args.shards_dir) if args.shards_dir
                 else out.parent / f"{out.stem}-shards")
    shard_dir.mkdir(parents=True, exist_ok=True)

    # 父进程登录一次，token 用环境变量发给分片：分片拿到 token 才起跑，
    # 免掉 32 份并发的 register 与 token，登录窗口从秒级压到毫秒级。
    headers, user_id = login(args.base_url, args.username, args.password)
    token = headers["Authorization"].split(" ", 1)[1]

    child_base = [sys.executable, "-u", str(Path(__file__).resolve()),
                  "--base-url", args.base_url, "--username", args.username,
                  "--password", args.password, "--levels", args.levels,
                  "--duration", str(args.duration), "--dur-factor", str(args.dur_factor),
                  "--dur-min", str(args.dur_min), "--dur-max", str(args.dur_max),
                  "--max-wall", str(args.max_wall), "--timeout", str(args.timeout),
                  "--warmup", str(args.warmup), "--max-err-rate", str(args.max_err_rate),
                  "--max-p95-ms", str(args.max_p95_ms), "--drop-ratio", str(args.drop_ratio),
                  "--tag", args.tag]
    if args.no_abort:
        child_base.append("--no-abort")

    print(f"\n=== 多进程加压：{procs} 个进程，每个跑完整阶梯 {args.levels or DEFAULT_LEVELS} "
          f"===\n总并发 = 档位 × {procs}\n父进程已登录，user_id={user_id}，"
          f"分片不再各自认证\n", flush=True)

    children: list[tuple[int, subprocess.Popen, Path]] = []
    for shard in range(procs):
        shard_out = shard_dir / f"shard{shard:02d}.json"
        cmd = child_base + ["--shard", f"{shard}/{procs}", "--out", str(shard_out)]
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONPATH=str(ROOT),
                   RAMP_TOKEN=token, RAMP_USER_ID=str(user_id))
        # stdout/stderr 继承：不做管道捕获，子进程的输出直接落到父进程控制台
        proc = subprocess.Popen(cmd, cwd=ROOT, env=env,
                                stdout=None, stderr=None)
        children.append((shard, proc, shard_out))
        print(f"  分片 {shard}/{procs} 已启动 pid={proc.pid} → {shard_out.name}",
              flush=True)

    try:
        for shard, proc, shard_out in children:
            code = proc.wait()
            print(f"  分片 {shard}/{procs} 退出码 {code}（{shard_out.name}）", flush=True)
    except KeyboardInterrupt:
        print("\n!! 人工中断，正在结束所有分片…", flush=True)
        for _, proc, _ in children:
            if proc.poll() is None:
                proc.terminate()
        for _, proc, _ in children:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        print("!! 分片已结束；已写出的分片仍会被合并", flush=True)

    shard_runs: list[dict] = []
    missing: list[str] = []
    for shard, _, shard_out in children:
        if shard_out.exists():
            try:
                shard_runs.append(json.loads(shard_out.read_text(encoding="utf-8")))
            except json.JSONDecodeError as exc:
                missing.append(f"{shard_out.name}（JSON 损坏：{exc}）")
        else:
            missing.append(shard_out.name)
    if missing:
        print(f"\n!! 缺 {len(missing)} 个分片结果：{', '.join(missing)}", flush=True)
    if not shard_runs:
        print("!! 没有任何分片产出结果，未写出合并文件", flush=True)
        return 2

    payload = aggregate(shard_runs, len(shard_runs), args)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'总并发':>7} {'时长':>6} {'请求':>8} {'吞吐':>8} {'p50':>7} {'p95':>7} "
          f"{'p99':>7} {'降级':>5} {'挂起':>5} {'错误':>6} {'客户端核':>8}", flush=True)
    for block in payload["phases"]:
        print(f"{block['total_concurrency']:>7} {block['duration_s']:>6.0f} "
              f"{block['requests']:>8} {block['throughput']:>8.1f} {block['p50']:>7.0f} "
              f"{block['p95']:>7.0f} {block['p99']:>7.0f} {block['degraded']:>5} "
              f"{block['hang_gt_10s']:>5} {block['failed']:>6} "
              f"{block['cpu_cores']:>8.2f}", flush=True)
    print(f"\n合并结果已写入 {out}（{len(shard_runs)} 个分片）", flush=True)
    print(f"中止点：{payload['aborted_at'] or '未触发'}", flush=True)

    if not args.keep_shards:
        for _, _, shard_out in children:
            shard_out.unlink(missing_ok=True)
        try:
            shard_dir.rmdir()
        except OSError:
            pass
    else:
        print(f"分片文件保留在 {shard_dir}", flush=True)
    return 0


def main() -> None:
    args = build_parser().parse_args()
    if args.procs > 1 and not args.shard:
        sys.exit(run_multi(args))
    sys.exit(run_single(args))


if __name__ == "__main__":
    main()
