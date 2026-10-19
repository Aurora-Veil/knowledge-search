"""从 example/reports.csv 抽检索词，生成 stress/queries.json。

只做抽取，不发请求。产物给 ramp_mixed.py 当检索词库：

    terms       行业分类里的叶子词（按出现次数排序）及其所属板块
    aliases     近义词对：标题里的「中文（English）」写法 + 少量人工补充
    titles      去掉年份、「（独占版）」等尾巴的报告标题，当长查询用
    industries  行业筛选用词，和 terms 同源

用法（仓库根目录）：
    $env:PYTHONIOENCODING='utf-8'
    python stress/scripts/build_queries.py
    python stress/scripts/build_queries.py --min-count 2 --out stress/queries.json
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]      # stress/scripts/… → 仓库根目录
CSV_PATH = ROOT / "example" / "reports.csv"
OUT_PATH = ROOT / "stress" / "queries.json"

CJK = re.compile(r"[\u4e00-\u9fa5]")

# 标题里的「中文（English）」：智能体（AI Agent）、虚拟现实(VR)、CRO（合同研究组织）
ALIAS_RE = re.compile(r"([\u4e00-\u9fa5A-Za-z0-9]{2,10})\s*[（(]\s*"
                     r"([A-Za-z][A-Za-z0-9 &/+.\-]{1,20})\s*[）)]")

# 这些词单独当检索词没有区分度，或者根本不是业务词
STOP = frozenset("""
其他 其它 综合 未知 相关 行业 产业 市场 企业 公司 产品 服务 技术 发展 趋势 分析
研究 报告 白皮书 中国 全球 国际 国内 领域 应用 解决方案 平台 系统 项目 案例 数据
制造 运营 管理 投资 融资 政策 标准 需求 供给 规模 增速 占比 情况 问题 建议 展望
""".split())

# 标题里被括号截断出来的碎片，不当近义词
JUNK_ALIAS = ("剖析", "洞察", "前瞻", "深度", "解读", "白皮书", "报告", "研究",
              "分析", "展望", "趋势", "如何", "什么")

# 语料里未必出现、但真实用户一定会混着打的近义词
CURATED = [
    ("人工智能", "AI"), ("大模型", "LLM"), ("大模型", "基础模型"),
    ("新能源汽车", "电动汽车"), ("新能源汽车", "EV"),
    ("半导体", "芯片"), ("半导体", "集成电路"),
    ("医疗健康", "大健康"), ("生物医药", "生物制药"),
    ("储能", "储能技术"), ("光伏", "太阳能光伏"),
    ("云计算", "云服务"), ("物联网", "IoT"),
    ("机器人", "机器人技术"), ("智能制造", "智能工厂"),
    ("短视频", "短视频平台"), ("直播电商", "直播带货"),
    ("跨境电商", "跨境电子商务"), ("数字经济", "数字化经济"),
    ("碳中和", "双碳"), ("氢能", "氢能源"),
    ("虚拟现实", "VR"), ("增强现实", "AR"),
    ("自动驾驶", "无人驾驶"), ("动力电池", "锂电池"),
]


def clean_cn(text: str) -> str:
    """'2026年中国智能体' → '智能体'；'年全球及中国电磁兼容' → '电磁兼容'。"""
    s = text.strip()
    for _ in range(3):
        s = re.sub(r"^[0-9]*年?", "", s) if re.match(r"^[0-9]*年", s) else s
        for pre in ("全球及中国", "中国及全球", "全球", "中国", "及", "和"):
            if s.startswith(pre):
                s = s[len(pre):]
                break
        else:
            break
    return s.strip()


def clean_title(text: str) -> str:
    t = re.sub(r"[（(](独占版|完整版|精华版|简版|公开版|2026年?版?)[）)]", "", text)
    t = re.sub(r"[（(]?20\d\d年?[）)]?", "", t)
    t = re.sub(r"^(中国|全球|国内)", "", t)
    t = re.sub(r"[《》\"“”]", "", t)
    return t.strip(" -_·、,，")


def ok_term(term: str) -> bool:
    return (2 <= len(term) <= 14 and bool(CJK.search(term))
            and term not in STOP and "|" not in term
            and not term.isdigit())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(CSV_PATH))
    ap.add_argument("--out", default=str(OUT_PATH))
    ap.add_argument("--min-count", type=int, default=2, help="词至少出现几次才收录")
    ap.add_argument("--max-terms", type=int, default=4000)
    ap.add_argument("--max-titles", type=int, default=2500)
    args = ap.parse_args()

    leaves: Counter = Counter()
    leaf_sector: dict[str, Counter] = defaultdict(Counter)
    sectors: Counter = Counter()
    titles: list[str] = []
    seen_titles: set[str] = set()
    alias_hits: Counter = Counter()
    rows = 0

    with open(args.csv, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            rows += 1
            raw = (row.get("industry") or "").strip()
            if raw:
                for part in raw.split("、"):
                    segs = [s.strip() for s in part.split("|") if s.strip()]
                    if len(segs) < 2:
                        continue
                    sector, leaf = segs[1], segs[-1]
                    if ok_term(sector):
                        sectors[sector] += 1
                    if ok_term(leaf) and ok_term(sector):
                        leaves[leaf] += 1
                        leaf_sector[leaf][sector] += 1

            title = (row.get("title") or "").strip()
            if not title:
                continue
            for m in ALIAS_RE.finditer(title):
                cn, en = clean_cn(m.group(1)), m.group(2).strip()
                if (2 <= len(cn) <= 8 and re.fullmatch(r"[\u4e00-\u9fa5]+", cn)
                        and ok_term(cn) and len(en) >= 2 and "+" not in en
                        and not cn.startswith(("从", "由", "为", "和", "与"))
                        and not any(w in cn for w in JUNK_ALIAS)):
                    alias_hits[(cn, en)] += 1
            cleaned = clean_title(title)
            if 6 <= len(cleaned) <= 42 and cleaned not in seen_titles:
                seen_titles.add(cleaned)
                titles.append(cleaned)

    terms = []
    for term, n in leaves.most_common(args.max_terms):
        if n < args.min_count:
            continue
        sector = leaf_sector[term].most_common(1)[0][0]
        terms.append({"t": term, "n": n, "s": sector})

    vocab = {t["t"] for t in terms}
    aliases: list[list[str]] = []
    seen_alias: set[tuple[str, str]] = set()
    seen_alias_lower: set[tuple[str, str]] = set()
    for (cn, en), n in alias_hits.most_common(120):
        key = (cn, en.lower())
        if key in seen_alias_lower:
            continue
        seen_alias_lower.add(key)
        seen_alias.add((cn, en))
        aliases.append([cn, en])
    for cn, en in CURATED:
        key = (cn, en)
        if key in seen_alias or cn not in vocab:
            continue
        seen_alias.add(key)
        aliases.append([cn, en])

    industries = sorted({t["t"] for t in terms if t["n"] >= 5})
    payload = {
        "meta": {
            "source": str(Path(args.csv).relative_to(ROOT)).replace("\\", "/"),
            "rows": rows,
            "built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "terms": len(terms),
            "sectors": len(sectors),
            "aliases": len(aliases),
            "titles": len(titles),
        },
        "sectors": [[s, n] for s, n in sectors.most_common(60)],
        "terms": terms,
        "aliases": aliases,
        "titles": titles[: args.max_titles],
        "industries": industries,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"读入 {rows} 行")
    print(f"板块 {len(sectors)} 个："
          + "、".join(f"{s}({n})" for s, n in sectors.most_common(12)))
    print(f"检索词 {len(terms)} 个（出现 ≥{args.min_count} 次）")
    print("  前 20：" + "、".join(f"{t['t']}({t['n']})" for t in terms[:20]))
    print(f"近义词对 {len(aliases)} 组：" + "、".join(f"{a}={b}" for a, b in aliases[:10]))
    print(f"长查询标题 {len(payload['titles'])} 条：" + " / ".join(titles[:3]))
    print(f"行业筛选用词 {len(industries)} 个")
    print(f"\n已写入 {out}（{out.stat().st_size / 1024:.0f} KB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
