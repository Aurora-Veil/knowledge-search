"""压测期间的轻量容器哨兵：每 2 s 采一次 docker stats + docker events。

比 container_metrics.py 轻得多（后者还要连 ES/PG 做深度采样），专门用来在
高并发压测时看**有没有容器先死**——OOMKilled / ExitCode!=0 / Exited。

用法：
    python stress/scripts/watch_containers.py --duration 300 --out stress/run/watch.json
压测结束后打印：各容器内存峰值/限额占比、CPU 峰值、是否出现过 OOM/退出。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

NAMES = ["api", "encoder", "es01", "es02", "es03", "pg", "mongo"]


def parse_size(text: str) -> float | None:
    """'2.44GiB' / '512MiB' / '1.2GB' → 字节。"""
    text = text.strip()
    for unit, mul in (("GiB", 1024 ** 3), ("MiB", 1024 ** 2), ("KiB", 1024),
                      ("GB", 1000 ** 3), ("MB", 1000 ** 2), ("kB", 1000), ("B", 1)):
        if text.endswith(unit):
            try:
                return float(text[:-len(unit)]) * mul
            except ValueError:
                return None
    return None


def docker_stats() -> dict[str, dict]:
    fmt = "{{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.CPUPerc}}\t{{.PIDs}}"
    res = subprocess.run(["docker", "stats", "--no-stream", "--format", fmt, *NAMES],
                         capture_output=True, text=True, timeout=30)
    out: dict[str, dict] = {}
    for line in res.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 5:
            continue
        used = parts[1].split("/")[0]
        out[parts[0].lstrip("/")] = {
            "mem": parse_size(used),
            "mem_pct": float(parts[2].rstrip("%")) if parts[2].rstrip("%") else None,
            "cpu": float(parts[3].rstrip("%")) if parts[3].rstrip("%") else None,
            "pids": int(parts[4]) if parts[4].isdigit() else None,
        }
    return out


def container_state() -> dict[str, dict]:
    """docker inspect：OOMKilled / ExitCode / Status，用来抓"已经死了"。"""
    res = subprocess.run(
        ["docker", "inspect", "--format",
         "{{.Name}}\t{{.State.Status}}\t{{.State.OOMKilled}}\t{{.State.ExitCode}}\t"
         "{{.RestartCount}}", *NAMES],
        capture_output=True, text=True, timeout=30)
    out: dict[str, dict] = {}
    for line in res.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 5:
            continue
        out[parts[0].lstrip("/")] = {"status": parts[1], "oom": parts[2] == "true",
                                     "exit": int(parts[3]) if parts[3].lstrip("-").isdigit() else None,
                                     "restarts": int(parts[4]) if parts[4].isdigit() else None}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=float, default=300.0)
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ready-url", default="http://127.0.0.1:8000/api/v1/health/ready")
    args = ap.parse_args()

    samples: list[dict] = []
    events: list[dict] = []
    stop = threading.Event()

    def event_watch() -> None:
        proc = subprocess.Popen(
            ["docker", "events", "--filter", "type=container", "--format",
             "{{.Time}}\t{{.Actor.Attributes.name}}\t{{.Action}}"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            encoding="utf-8", errors="replace")
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                if stop.is_set():
                    break
                parts = line.rstrip("\n").split("\t")
                if len(parts) == 3:
                    events.append({"ts": parts[0], "name": parts[1], "action": parts[2]})
        finally:
            proc.terminate()

    th = threading.Thread(target=event_watch, daemon=True)
    th.start()

    t0 = time.perf_counter()
    print(f"哨兵启动，采样 {args.duration:.0f}s，间隔 {args.interval:.0f}s", flush=True)
    while time.perf_counter() - t0 < args.duration:
        t = round(time.perf_counter() - t0, 1)
        stats = docker_stats()
        state = container_state()
        samples.append({"t": t, "stats": stats, "state": state})
        dead = {k: v for k, v in state.items() if v["status"] != "running" or v["oom"]}
        if dead:
            print(f"  !! t={t:.0f}s 异常容器：{dead}", flush=True)
        time.sleep(args.interval)

    stop.set()
    time.sleep(0.5)

    # 汇总
    def peak(name: str, key: str):
        vals = [s["stats"].get(name, {}).get(key) for s in samples]
        vals = [v for v in vals if v is not None]
        return max(vals) if vals else None

    print(f"\n{'容器':<9} {'内存峰值':>10} {'峰值%':>7} {'CPU峰':>7} {'PIDs峰':>7} "
          f"{'OOM':>5} {'退出码':>6} {'重启':>5}", flush=True)
    for name in NAMES:
        mem = peak(name, "mem")
        print(f"{name:<9} {mem / 1024 ** 3 if mem else 0:>9.2f}G {str(peak(name, 'mem_pct')):>7} "
              f"{str(peak(name, 'cpu')):>7} {str(peak(name, 'pids')):>7} "
              f"{'是' if any(s['state'].get(name, {}).get('oom') for s in samples) else '否':>5} "
              f"{str(samples[-1]['state'].get(name, {}).get('exit')):>6} "
              f"{str(samples[-1]['state'].get(name, {}).get('restarts')):>5}", flush=True)

    interesting = [e for e in events
                   if any(k in e["action"] for k in ("die", "oom", "kill", "stop",
                                                     "destroy", "restart", "unhealthy"))]
    print(f"\n容器生死/健康事件：{len(interesting)} 条", flush=True)
    for event in interesting[:40]:
        print(f"  {event['ts']}  {event['name']:<9} {event['action']}", flush=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"samples": samples, "events": events},
                              ensure_ascii=False), encoding="utf-8")
    print(f"\n样本已写入 {out}（{len(samples)} 个采样点）", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
