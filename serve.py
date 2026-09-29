"""API 启动入口：N 个单进程实例 + 本地转发层。

Windows 上多个进程共用同一个监听 socket 会出现 accept 抢 socket（表现为连接被接受但没人处理、
客户端挂满超时、服务端日志里什么都没有），所以这里让每个实例各占一个端口，
父进程做一个按连接轮询的转发层，对外仍然是单个 127.0.0.1:8000。

用法：
    python run.py                         # 实例数 = WEB_WORKERS（默认 4），对外 8000，实例在 8001+
    python run.py --instances 1 --reload  # 单实例直跑，开发用
    python run.py --response-timeout 60   # 请求发出后后端一直不回应的上限，默认 30 秒
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

CONNECT_TIMEOUT_S = 3.0        # 连接实例的上限
FAILS_TO_EJECT = 2             # 连续失败几次后短暂摘除
EJECT_COOLDOWN_S = 5.0
STATS_EVERY_S = 60.0


def child_env(es_workers: int) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["WEB_WORKERS"] = "1"
    if not os.getenv("ES_SEARCH_WORKERS"):        # 外部显式设了就别覆盖
        env["ES_SEARCH_WORKERS"] = str(es_workers)
    return env


def child_code(port: int) -> str:
    return (
        "import serve, uvicorn;"
        "serve.watch_parent();"
        f"uvicorn.run('app.main:app', host='127.0.0.1', port={port},"
        " workers=1, reload=False, log_level='info')"
    )


def watch_parent() -> None:
    """父进程没了就自己退出，避免启动器被强杀后留下占着端口的实例。"""
    if os.name != "nt":
        return
    import ctypes
    import threading

    SYNCHRONIZE = 0x00100000
    handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, os.getppid())
    if not handle:
        return

    def wait() -> None:
        ctypes.windll.kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
        os._exit(0)

    threading.Thread(target=wait, daemon=True).start()


def spawn_instances(instances: int, base_port: int, es_workers: int,
                    log_dir: Path) -> list:
    log_dir.mkdir(parents=True, exist_ok=True)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    procs = []
    for i in range(instances):
        port = base_port + i
        log = open(log_dir / f"worker-{port}.log", "w", encoding="utf-8")
        p = subprocess.Popen([sys.executable, "-c", child_code(port)],
                             cwd=ROOT, env=child_env(es_workers),
                             stdout=log, stderr=subprocess.STDOUT,
                             creationflags=flags)
        procs.append((port, p, log))
        print(f"[启动] 实例 127.0.0.1:{port} pid={p.pid} "
              f"ES_SEARCH_WORKERS={os.getenv('ES_SEARCH_WORKERS') or es_workers}",
              flush=True)
    return procs


def tail(path: Path, lines: int = 15) -> str:
    try:
        return "".join(path.read_text(encoding="utf-8", errors="replace").splitlines(True)[-lines:])
    except OSError:
        return ""


def wait_ready(port: int, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    req = (b"GET /api/v1/health HTTP/1.1\r\nHost: 127.0.0.1\r\n"
           b"Connection: close\r\n\r\n")
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0) as s:
                s.sendall(req)
                if b" 200 " in s.recv(128):
                    return True
        except OSError:
            pass
        time.sleep(0.4)
    return False


def port_is_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def run_single(port: int, reload: bool) -> None:
    import uvicorn

    print(f"[启动] 单实例直跑 127.0.0.1:{port}"
          f"（ES_SEARCH_WORKERS={os.getenv('ES_SEARCH_WORKERS') or '自适应'}）", flush=True)
    uvicorn.run("app.main:app", host="127.0.0.1", port=port,
                workers=1, reload=reload, log_level="info")


class Backend:

    def __init__(self, port: int) -> None:
        self.port = port
        self.fails = 0
        self.down_until = 0.0

    def available(self, now: float) -> bool:
        return now >= self.down_until

    def ok(self) -> None:
        self.fails = 0
        self.down_until = 0.0

    def fail(self, now: float) -> bool:
        """返回 True 表示这一次把它摘除了。"""
        self.fails += 1
        if self.fails >= FAILS_TO_EJECT and now >= self.down_until:
            self.down_until = now + EJECT_COOLDOWN_S
            return True
        return False


class Relay:

    def __init__(self, ports: list[int], port: int, response_timeout: float,
                 alive=None) -> None:
        self.backends = [Backend(p) for p in ports]
        self.port = port
        self.response_timeout = response_timeout
        self.alive = alive or (lambda _port: True)   # 进程还在不在；退出的实例永久移出轮询
        self._dead_logged: set[int] = set()
        self._next = 0
        self.conns = 0
        self.total = 0
        self.ejections = 0
        self.timeouts = 0

    def _pick(self) -> Backend:
        now = time.monotonic()
        live = [b for b in self.backends if self.alive(b.port)]
        for b in self.backends:
            if b not in live and b.port not in self._dead_logged:
                self._dead_logged.add(b.port)
                print(f"[转发] 实例 {b.port} 已退出，移出轮询（重启启动器才能恢复）",
                      flush=True)
        pool = [b for b in live if b.available(now)] or live or self.backends
        backend = pool[self._next % len(pool)]
        self._next += 1
        return backend

    async def _pump(self, reader: asyncio.StreamReader,
                    writer: asyncio.StreamWriter, on_data=None) -> None:
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                if on_data:
                    on_data()
                writer.write(data)
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError,
                asyncio.IncompleteReadError, OSError):
            pass

    async def _watch(self, writer: asyncio.StreamWriter, state: dict) -> None:
        """请求已经转发出去、后端却一直不回应时掐掉，避免客户端永久挂住。"""
        while True:
            await asyncio.sleep(1.0)
            since = state.get("pending_since") or 0.0
            if since and time.monotonic() - since > self.response_timeout:
                self.timeouts += 1
                print(f"[转发] 后端 {self.response_timeout:.0f} 秒无响应，断开该连接",
                      flush=True)
                writer.close()
                return

    async def _on_conn(self, reader: asyncio.StreamReader,
                       writer: asyncio.StreamWriter) -> None:
        self.conns += 1
        self.total += 1
        backend = self._pick()
        try:
            back_r, back_w = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", backend.port), CONNECT_TIMEOUT_S)
        except (OSError, asyncio.TimeoutError) as exc:
            if backend.fail(time.monotonic()):
                self.ejections += 1
            print(f"[转发] 实例 {backend.port} 连不上，回 502："
                  f"{type(exc).__name__}: {exc}", flush=True)
            try:
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\n"
                             b"Content-Length: 0\r\nConnection: close\r\n\r\n")
                await writer.drain()
            except OSError:
                pass
            writer.close()
            self.conns -= 1
            return
        backend.ok()

        state: dict = {"pending_since": 0.0}
        watchdog = asyncio.create_task(self._watch(writer, state))
        try:
            await asyncio.gather(
                self._pump(reader, back_w,
                           lambda: state.__setitem__("pending_since", time.monotonic())),
                self._pump(back_r, writer,
                           lambda: state.__setitem__("pending_since", 0.0)),
                return_exceptions=True)
        finally:
            watchdog.cancel()
            self.conns -= 1
            for w in (writer, back_w):
                try:
                    w.close()
                except OSError:
                    pass
            try:
                await back_w.wait_closed()
            except (OSError, asyncio.CancelledError):
                pass

    async def serve(self) -> None:
        server = await asyncio.start_server(self._on_conn, "127.0.0.1", self.port)
        ports = [b.port for b in self.backends]
        print(f"[启动] 转发层 127.0.0.1:{self.port} -> "
              f"{['127.0.0.1:%d' % p for p in ports]}", flush=True)
        async with server:
            while True:
                await asyncio.sleep(STATS_EVERY_S)
                now = time.monotonic()
                down = [b.port for b in self.backends if not b.available(now)]
                print(f"[转发] 累计连接 {self.total} 在途 {self.conns} "
                      f"摘除中 {down or '无'} 累计摘除 {self.ejections} "
                      f"超时断开 {self.timeouts}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="API 启动入口")
    ap.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")),
                    help="对外监听端口，默认 8000")
    ap.add_argument("--instances", type=int,
                    default=int(os.getenv("WEB_WORKERS", "4")),
                    help="实例数，默认等于 WEB_WORKERS；1 = 单实例直跑")
    ap.add_argument("--reload", action="store_true", help="仅单实例时可用，改代码自动重启")
    ap.add_argument("--response-timeout", type=float, default=30.0,
                    help="请求已发出、后端一直不回应的上限秒数，默认 30")
    args = ap.parse_args()

    instances = max(1, args.instances)
    os.environ["WEB_WORKERS"] = str(instances)     # 让 app.config 按真实实例数做聚合校验

    from app.config import ES_SEARCH_WORKERS      # noqa: E402  导入即校验（PG / ES / 编码超时）

    if instances == 1:
        run_single(args.port, args.reload)
        return 0
    if args.reload:
        print("--reload 只在 --instances 1 下有效", file=sys.stderr)
        return 2

    base_port = args.port + 1
    for port in [args.port, *range(base_port, base_port + instances)]:
        if not port_is_free(port):
            print(f"端口 {port} 被占用：可能是上一轮没退干净的实例，先清掉再启动",
                  file=sys.stderr)
            return 1

    log_dir = ROOT / "logs"
    procs = spawn_instances(instances, base_port, ES_SEARCH_WORKERS, log_dir)
    proc_by_port = {port: p for port, p, _log in procs}
    try:
        for port, _p, _log in procs:
            if not wait_ready(port):
                print(f"实例 {port} 启动失败：{log_dir / f'worker-{port}.log'}",
                      file=sys.stderr)
                print(tail(log_dir / f"worker-{port}.log"), file=sys.stderr)
                return 1
        print(f"[就绪] {instances} 个实例全部可用，对外 127.0.0.1:{args.port}", flush=True)

        relay = Relay([p for p, _x, _y in procs], args.port, args.response_timeout,
                      alive=lambda port: proc_by_port[port].poll() is None)
        asyncio.run(relay.serve())
    except KeyboardInterrupt:
        print("\n[退出] 收到中断，停实例", flush=True)
    finally:
        for _port, p, _log in procs:
            if p.poll() is None:
                try:
                    p.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt"
                                  else signal.SIGTERM)
                except OSError:
                    p.terminate()
        for _port, p, log in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
            log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
