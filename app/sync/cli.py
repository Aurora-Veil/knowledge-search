"""命令入口：`python -m app.sync <子命令>`（顶层 `full_sync.py` 是等价兼容入口）。

子命令：init（建索引）/ full（全量灌）/ recreate（删索引重建 + 全量灌）/
        one（写库后单条同步）/ reconcile（对账，可选 --fix）。
"""
from __future__ import annotations

import argparse
import sys

from ..config import DEFAULT_PROJECT_ID, OBJECT_TYPES

# 子命令已注册、动作尚未落地时的退出码（区别于参数错误 2 / 运行失败 1）
PENDING_EXIT = 3


def _launch_name() -> str:
    """prog 名按启动方式显示：`python -m app.sync` 与 `python full_sync.py` 各显示自己。"""
    name = sys.argv[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return "python -m app.sync" if name in ("", "__main__.py") else name


def _pending(what: str, planned_in: str) -> int:
    """入口已注册、动作未实现时说明归属（不给 traceback）。"""
    print(f"[未实现] {what} —— 将在「{planned_in}」落地（app/sync/ 对应模块）", file=sys.stderr)
    return PENDING_EXIT


def _run_init(_args: argparse.Namespace) -> int:
    return _pending("init：按 mapping/*.json 建缺失的索引", "索引建删与差异提示")


def _run_full(args: argparse.Namespace) -> int:
    if args.recreate:
        return _pending("full --recreate：drop → create → 全量重灌", "索引建删与差异提示 + 全量灌与真实计数")
    return _pending("full：全量灌 Mongo → ES", "全量灌与真实计数")


def _run_recreate(_args: argparse.Namespace) -> int:
    return _pending("recreate：drop → create → 全量重灌", "索引建删与差异提示 + 全量灌与真实计数")


def _run_one(_args: argparse.Namespace) -> int:
    return _pending("one：单条 upsert / 删除传播", "写后同步与删除传播")


def _run_reconcile(args: argparse.Namespace) -> int:
    what = "reconcile --fix：删孤儿 + 重灌缺失" if args.fix else "reconcile：只报告漂移"
    return _pending(what, "孤儿缺失比对与修复")


def _switch_table(prog: str, cmds: list[tuple[str, str, argparse.ArgumentParser]]) -> str:
    """由各子命令解析器自身的 usage 生成开关表：与开关定义同源，不会写歪。

    顶层帮助因此能一眼看全「每个子命令有哪些开关」，不必逐个 --help 去翻。
    """
    rows = []
    for name, one_line, sp in cmds:
        usage = sp.format_usage().strip()
        prefix = f"usage: {prog} {name}"
        switches = usage[len(prefix):].strip() if usage.startswith(prefix) else usage
        for dead in ("[-h] ", "[-h]"):
            if switches.startswith(dead):
                switches = switches[len(dead):].strip()
                break
        switches = " ".join(switches.split())  # usage 自带换行/缩进，压成单行免排参差
        rows.append((name, switches or "（无开关）", one_line))

    width = max(len(name) for name, _, _ in rows)
    lines = ["子命令与开关（两个入口通用）："]
    for name, switches, one_line in rows:
        lines.append(f"  {name.ljust(width)}  {switches}")
        lines.append(f"  {' ' * width}    └ {one_line}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    prog = _launch_name()
    parser = argparse.ArgumentParser(
        prog=prog,
        description="MongoDB(knowledge_db) → Elasticsearch(knowledge_*) 同步工具：建索引 / 全量灌 / 单条同步 / 对账。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", title="子命令")
    cmds: list[tuple[str, str, argparse.ArgumentParser]] = []

    sp = sub.add_parser("init", help="按 mapping/*.json 建缺失的索引（不碰已有索引）")
    sp.set_defaults(func=_run_init)
    cmds.append(("init", "按 mapping/*.json 建缺失的索引（不碰已有索引）", sp))

    sp = sub.add_parser("full", help="全量灌 Mongo → ES（默认不动已有索引）")
    sp.add_argument("--recreate", action="store_true",
                    help="先 drop 再按 mapping 重建索引，然后全量重灌（破坏性）")
    sp.add_argument("--dry-run", action="store_true", help="只报将要写入的条数，不写 ES")
    sp.set_defaults(func=_run_full)
    cmds.append(("full", "全量灌 Mongo → ES（默认不动已有索引）", sp))

    sp = sub.add_parser("recreate", help="等价 full --recreate：删索引重建后全量重灌")
    sp.add_argument("--dry-run", action="store_true", help="只报将要 drop/创建/写入的内容，不执行")
    sp.set_defaults(func=_run_recreate)
    cmds.append(("recreate", "等价 full --recreate：删索引重建后全量重灌", sp))

    sp = sub.add_parser("one", help="写库后单条同步（对象已删则从 ES 删除）")
    sp.add_argument("--type", required=True, choices=list(OBJECT_TYPES), help="对象类型（决定查哪个集合/索引）")
    sp.add_argument("--oirf-id", required=True, metavar="OIRF_ID", help="项目内业务 id，如 evidence:E001")
    sp.add_argument("--project-id", type=int, default=DEFAULT_PROJECT_ID,
                    help=f"项目 ID；缺省 {DEFAULT_PROJECT_ID}（当前项目）")
    sp.set_defaults(func=_run_one)
    cmds.append(("one", "写库后单条同步（对象已删则从 ES 删除）", sp))

    sp = sub.add_parser("reconcile", help="对账 ES ↔ Mongo，列出孤儿/缺失（默认只报告）")
    sp.add_argument("--type", choices=list(OBJECT_TYPES), help="只对账某一类型；缺省三类全查")
    sp.add_argument("--fix", action="store_true", help="删 ES 孤儿 + 重灌缺失（唯一会改 ES 的路径）")
    sp.set_defaults(func=_run_reconcile)
    cmds.append(("reconcile", "对账 ES ↔ Mongo，列出孤儿/缺失（默认只报告）", sp))

    parser.epilog = (
        _switch_table(prog, cmds) + "\n\n"
        "常用示例：\n"
        f"  {prog} init\n"
        f"  {prog} full\n"
        f"  {prog} full --recreate\n"
        f"  {prog} one --type evidence --oirf-id evidence:E001\n"
        f"  {prog} reconcile\n"
        f"  {prog} reconcile --fix\n\n"
        "两个入口等价：python -m app.sync 与 python full_sync.py 接受同一套子命令与开关。\n"
        "破坏性动作必须显式开关：--recreate（删索引重建）、reconcile --fix（改 ES）。"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:  # 没给子命令：给帮助，而不是报参数错
        parser.print_help()
        return 0
    return func(args)


__all__ = ["build_parser", "main", "PENDING_EXIT"]
