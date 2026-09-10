"""命令入口：`python -m app.sync <子命令>`（顶层 `full_sync.py` 是等价兼容入口）。

子命令：init（建索引）/ full（全量灌）/ recreate（删索引重建 + 全量灌）/
        one（写库后单条同步）/ reconcile（对账，可选 --fix）。
"""
from __future__ import annotations

import argparse
import sys

from ..config import DEFAULT_PROJECT_ID, INDEX_BY_TYPE, OBJECT_TYPES
from ..db import get_es
from . import admin, full, one, reconcile


def _launch_name() -> str:
    """prog 名按启动方式显示：`python -m app.sync` 与 `python full_sync.py` 各显示自己。"""
    name = sys.argv[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return "python -m app.sync" if name in ("", "__main__.py") else name


def _index_plan(es) -> list[tuple[str, str, bool, list[str]]]:
    """逐类型一行：(type, index, 是否已存在, 现有 mapping 与 mapping 文件的差异行)。"""
    plan = []
    for t in OBJECT_TYPES:
        index = INDEX_BY_TYPE[t]
        present, diff = admin.inspect_index(index, t, es)
        plan.append((t, index, present, diff))
    return plan


def _print_diff(t: str, diff: list[str], indent: str = "        ") -> None:
    print(f"{indent}现有 mapping 与 mapping/{admin.MAPPING_FILE[t]} 有 {len(diff)} 处差异：")
    for line in diff:
        print(f"{indent}  {line}")


def _run_init(_args: argparse.Namespace) -> int:
    """按 mapping/*.json 建缺失的索引；已存在的原样跳过，绝不动索引定义。"""
    prog = _launch_name()
    es = get_es()
    for t, index, present, diff in _index_plan(es):
        if present:
            print(f"[跳过] {index} 已存在，索引定义未改动")
            if diff:
                _print_diff(t, diff)
                print(f"       如需按文件重建：{prog} recreate")
        else:
            admin.create(index, t, es)
            print(f"[创建] {index} <- mapping/{admin.MAPPING_FILE[t]}")
    return 0


def _sync(recreate: bool, dry_run: bool) -> int:
    """索引准备（默认跳过已有索引；--recreate 才 drop+create）→ 全量灌 → 报实际入库条数。"""
    prog = _launch_name()
    es = get_es()
    plan = _index_plan(es)

    if dry_run:
        for t, index, present, diff in plan:
            will_write = f"将全量重灌（预计写入 {full.count_source(t)} 条，按 Mongo 现有条数）"
            if recreate:
                step = "将删除（当前存在）" if present else "当前不存在，无需删除"
                print(f"[计划] {index}：{step} → 将按 mapping/{admin.MAPPING_FILE[t]} 创建 → {will_write}")
            else:
                step = ("已存在，将跳过（索引定义不动）" if present
                        else f"当前不存在，将按 mapping/{admin.MAPPING_FILE[t]} 创建")
                print(f"[计划] {index}：{step} → {will_write}")
            if diff:
                _print_diff(t, diff, indent="       ")
        print("[预演] 未执行任何删除/创建/写入")
        return 0

    for t, index, present, diff in plan:
        if recreate:
            if diff:
                print(f"[差异] {index}：现有 mapping 与 mapping/{admin.MAPPING_FILE[t]} 有 {len(diff)} 处差异，重建后按文件生效：")
                for line in diff:
                    print(f"         {line}")
            if present:
                admin.drop(index, es)
                print(f"[删除] {index}")
            admin.create(index, t, es)
            print(f"[创建] {index} <- mapping/{admin.MAPPING_FILE[t]}")
        elif present:
            print(f"[跳过] {index} 已存在，索引定义未改动")
            if diff:
                _print_diff(t, diff)
                print(f"       如需按文件重建：{prog} recreate")
        else:
            admin.create(index, t, es)
            print(f"[创建] {index} <- mapping/{admin.MAPPING_FILE[t]}")

    results = full.sync_all(es=es)
    ok = failed = 0
    for t in OBJECT_TYPES:
        r = results[t]
        ok += r["ok"]
        failed += r["failed"]
        tail = f"，失败 {r['failed']} 条" if r["failed"] else ""
        print(f"[重灌] {r['index']}：实际入 ES {r['ok']} 条{tail}")
        for line in r["error_lines"]:
            print(f"        {line}")
    print(f"[完成] 实际入 ES {ok} 条" + (f"，失败 {failed} 条" if failed else "") + "（Mongo 权威数据未改动）")
    return 1 if failed else 0


def _run_full(args: argparse.Namespace) -> int:
    return _sync(recreate=bool(args.recreate), dry_run=bool(args.dry_run))


def _run_recreate(args: argparse.Namespace) -> int:
    """等价 `full --recreate`：drop → create → 全量重灌。"""
    return _sync(recreate=True, dry_run=bool(args.dry_run))


def _run_one(args: argparse.Namespace) -> int:
    """写库后单条同步（对象已删则从 ES 删除），手工重放/验证用。"""
    try:
        res = one.sync_one(args.project_id, args.oirf_id, args.type)
    except Exception as exc:  # ES 不可用/写入失败：报出来并以非 0 退出，绝不静默
        print(f"[失败] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if res["action"] == "indexed":
        print(f"[已同步] {res['index']} _id={res['id']} <- Mongo {args.type} "
              f"project_id={args.project_id} {args.oirf_id}")
        if res.get("created_index"):
            print(f"        [已建索引] {res['index']} 原先不存在，已按 mapping/*.json 新建"
                  f"（否则 ES 会自动建出没有 mapping 的索引）")
    elif res["action"] == "deleted":
        print(f"[已删除] {res['index']} _id={','.join(res['ids'])}（Mongo 已无该对象）")
    else:
        print(f"[无需动作] {res['index']} 与 Mongo 都没有 "
              f"project_id={args.project_id} {args.oirf_id}")
        if res.get("missing_index"):
            print(f"        （该索引当前不存在；要建它：python -m app.sync init）")
    return 0


ID_LIMIT = 10  # 明细最多列这么多条；计数永远是全量


def _ids_block(label: str, ids: list[str]) -> None:
    print(f"  {label} {len(ids)} 条：")
    for i in ids[:ID_LIMIT]:
        print(f"    {i}")
    if len(ids) > ID_LIMIT:
        print(f"    … 另有 {len(ids) - ID_LIMIT} 条（略）")


def _run_reconcile(args: argparse.Namespace) -> int:
    """对账 ES ↔ Mongo：默认只报告；--fix 才删孤儿 + 重灌缺失。"""
    prog = _launch_name()
    types = [args.type] if args.type else list(OBJECT_TYPES)
    reports = reconcile.compare(types)

    orphans = sum(len(r["orphans"]) for r in reports)
    missing = sum(len(r["missing"]) for r in reports)
    drift = orphans + missing
    no_index = [r for r in reports if not r["index_exists"]]
    uncompared = sum(r["mongo"] for r in no_index)
    checkable = [r for r in reports if r["index_exists"]]

    for r in reports:
        if not r["index_exists"]:
            print(f"[{r['index']}] 索引不存在 —— Mongo 有 {r['mongo']} 条无法比对"
                  f"（先跑 {prog} init / recreate）")
            continue
        head = f"[{r['index']}] Mongo {r['mongo']} 条 / ES {r['es']} 条"
        if not (r["orphans"] or r["missing"]):
            print(f"{head} —— 零漂移")
            continue
        print(head)
        if r["orphans"]:
            _ids_block("孤儿（ES 有 Mongo 无）", r["orphans"])
        if r["missing"]:
            _ids_block("缺失（Mongo 有 ES 无）", r["missing"])

    # 索引缺失时不能下"零漂移"结论 —— 那些文档根本没参与比对（本轮验收发现的缺陷）
    if no_index:
        print(f"[结论] 无法完整对账：{len(no_index)} 个索引不存在，Mongo 侧 {uncompared} 条未参与比对"
              f" —— 先跑 {prog} init / recreate")

    if drift == 0 and not no_index:
        print("[结论] 零漂移 —— 两边 _id 集合逐类型完全一致")
        return 0

    if drift:
        print(f"[结论] 漂移 {drift} 处（孤儿 {orphans} / 缺失 {missing}）")
        if not args.fix:
            print(f"       本次只报告、未改任何数据；要清理：{prog} reconcile --fix")
    elif args.fix:
        print("[修复] 可对账的类型没有孤儿/缺失，无需修复")

    if args.fix and drift:
        res = reconcile.fix(checkable)
        print(f"[修复] 已删除孤儿 {res['deleted']} 条 / 已重灌缺失 {res['reindexed']} 条")
        for line in res["errors"]:
            print(f"        {line}")
        left = reconcile.drift_count(reconcile.compare([r["type"] for r in checkable]))
        print(f"[复核] 修复后再对账：漂移 {left} 处" + ("（已归零）" if left == 0 else "（仍有残留）"))
        if left:
            return 1

    return 1 if no_index else 0


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


__all__ = ["build_parser", "main"]
