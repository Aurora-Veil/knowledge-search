"""按生产报告的分布随机造 10 万级报告，直接 bulk 进独立压测索引。

不套模板，而是从 example/reports.json 真实语料重组：标题取真实标题做变异（换年份、换主体行业、
冒号后的卖点换成另一条真实卖点、按真实占比增删“（独占版）”），摘要取真实摘要做句级拼接并让它引用
自己的标题，长度/占比都对齐真实分布（`--stats` 可打印真实 vs 生成对照）。

mapping 与向量文本口径沿用生产（mapping/report_mapping.json、embedding/fields.json
的 report = title + summary）。生产索引 knowledge_report_index 一个字不改。

用法（仓库根目录）：
    $env:PYTHONIOENCODING='utf-8'; $env:PYTHONPATH=(Get-Location).Path
    python stress/make_reports_stress.py --stats 5000                  # 看分布像不像（不连 ES）
    python stress/make_reports_stress.py --dry-run 5                   # 看几条样本
    python stress/make_reports_stress.py --count 100000 --recreate     # 建索引 + 灌 10 万

向量：ENCODER_URL 有值就走编码服务（kind=passage，单请求 ≤ 256 条），否则用进程内模型
（--in-process 可强制）。压测索引默认 3 分片 0 副本：3 个数据节点各担一份，副本少一半写入。

清理：DELETE /knowledge_report_stress
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
import re
import statistics
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import es_auth, es_hosts                     # noqa: E402
from embedding.config import ENCODER_URL                     # noqa: E402
from embedding.spec import MODEL, build_text, text_hash      # noqa: E402

SOURCE_PATH = ROOT / "example" / "reports.json"
MAPPING_PATH = ROOT / "mapping" / "report_mapping.json"
TYPE = "report"

TITLE_KINDS = ["行业概览", "行业研究报告", "市场洞察", "白皮书", "市场简报",
               "品牌推荐", "深度报告", "投资价值分析", "行业研究", "市场研究"]
CN_NUM = "二三四五六七八九"

# 真实语料实测占比
YEAR_COUNTS = {"2018": 112, "2019": 904, "2020": 841, "2021": 757, "2022": 1077,
               "2023": 595, "2024": 350, "2025": 580, "2026": 298}
INDUSTRY_COUNT_WEIGHTS = [1152, 302, 1360, 1202, 460, 514, 524]  # 每篇 0..6+ 个 industry
LAYOUT_WEIGHTS = [4209, 1305]                                    # 横版 / 竖版
P_EXCLUSIVE = 0.252                                              # 标题带（独占版）
P_COLON = 0.327                                                  # 标题带 “：” 卖点
P_SHORT_SUMMARY = 0.158                                          # 摘要 <50 字


def load_corpus(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["reports"]


def build_pools(reports: list[dict]) -> dict:
    industries: collections.Counter = collections.Counter()
    co: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    sentences: list[str] = []
    for r in reports:
        names = r.get("industry") or []
        industries.update(names)
        for name in names:                                       # 真实共现，用来抽同篇的其他 industry
            co[name].update(n for n in names if n != name)
        body = r.get("summary") or ""
        for part in body.split("。"):
            part = part.strip()
            if 12 <= len(part) <= 400:
                sentences.append(part)
    names = list(industries)
    top = [n for n in sorted(names, key=len, reverse=True)[:400] if len(n) >= 3]
    titles = [r["title"] for r in reports if r.get("title")]
    return {
        "industries": names,
        "industry_weights": list(industries.values()),
        "industry_re": re.compile("|".join(re.escape(n) for n in top)),
        "co": {k: (list(v), list(v.values())) for k, v in co.items()},
        "titles": titles,
        "summaries": [r["summary"] for r in reports if r.get("summary")],
        "long_summaries": [r["summary"] for r in reports if len(r.get("summary") or "") >= 50],
        "sentences": list(dict.fromkeys(sentences)),
        "sells": list(dict.fromkeys(t.split("：", 1)[1] for t in titles if "：" in t)),
        "real_industry_counts": [len(r.get("industry") or []) for r in reports],
        "real_layouts": [r.get("layout") for r in reports],
        "real_years": [(r.get("publish_date") or "")[:4] for r in reports],
        "title_uses": collections.Counter(),
    }


def weighted_choice(rng: random.Random, items: list, weights: list):
    return rng.choices(items, weights=weights, k=1)[0]


def _swap_industry(rng: random.Random, pools: dict, title: str) -> str:
    hit = pools["industry_re"].search(title)
    if not hit:
        return title
    if rng.random() < 0.5:                                       # 一半按真实频率、一半均匀，留住长尾词
        new = weighted_choice(rng, pools["industries"], pools["industry_weights"])
    else:
        new = rng.choice(pools["industries"])
    return title[:hit.start()] + new + title[hit.end():]


def make_title(rng: random.Random, pools: dict, year: str) -> str:
    if rng.random() < 0.9:                                       # 真实标题变异
        title = rng.choice(pools["titles"])
        if re.search(r"(19|20)\d{2}", title):
            title = re.sub(r"(19|20)\d{2}", year, title, count=1)
        if rng.random() < 0.8:                                   # 换主体行业（也压低重复标题）
            title = _swap_industry(rng, pools, title)
        if rng.random() < 0.35:                                  # 冒号后换成另一条真实卖点
            head = title.split("：", 1)[0].replace("（独占版）", "")
            title = f"{head}：{rng.choice(pools['sells'])}"
    else:                                                        # 少量模板
        if rng.random() < 0.5:
            topic = weighted_choice(rng, pools["industries"], pools["industry_weights"])
        else:
            topic = rng.choice(pools["industries"])
        head = f"{year}年中国{topic}{rng.choice(TITLE_KINDS)}"
        title = f"{head}：{rng.choice(pools['sells'])}" if rng.random() < 0.5 else head

    bare = title.replace("（独占版）", "").strip()
    want_exclusive = rng.random() < P_EXCLUSIVE
    if rng.random() < P_COLON:                                   # 真实里 32.7% 带 “：卖点”
        if "：" not in bare:
            bare = f"{bare}：{rng.choice(pools['sells'])}"
    elif "：" in bare:
        bare = bare.split("：", 1)[0]
    bare = bare.replace("（独占版）", "").strip()                 # 换进来的卖点可能自带
    if len(bare) > 95:                                          # 真实最长 107（含（独占版）6 字）
        bare = bare.split("：", 1)[0] if "：" in bare else bare[:95]
    return f"{bare}（独占版）" if want_exclusive else bare


def make_summary(rng: random.Random, pools: dict, title: str) -> str:
    if rng.random() < P_SHORT_SUMMARY:                           # 短摘要（真实里 15.8%）
        return title[:rng.randint(4, 22)]

    src = rng.choice(pools["summaries"])
    if rng.random() < 0.3 and len(src) >= 50:                     # 30% 直接用整段真实摘要
        return _reference(rng, src, title)

    sents = [s.strip() for s in src.split("。") if s.strip()]
    if not sents:
        return title[:20]

    start = rng.randrange(len(sents))
    parts = sents[start:start + rng.randint(1, 3)]
    target = min(len(rng.choice(pools["long_summaries"])), 1200)  # 长度按真实长摘要分布抽
    while len("。".join(parts)) < target and len(parts) < 8:
        parts.append(rng.choice(pools["sentences"]))
    text = "。".join(parts) + "。"
    if len(text) > target * 1.25:                                 # 收尾句别把长度拉飞
        cut = text.rfind("。", 0, int(target * 1.25))
        if cut >= target * 0.8:
            text = text[:cut + 1]
    return _reference(rng, text, title)


def _reference(rng: random.Random, text: str, title: str) -> str:
    if "《" in text and rng.random() < 0.6:                       # 让摘要引用自己的标题
        text = re.sub(r"《[^》]{0,60}》", f"《{title}》", text, count=1)
    return text


def make_doc(i: int, pools: dict, rng: random.Random, seed: int) -> dict:
    year = weighted_choice(rng, list(YEAR_COUNTS), list(YEAR_COUNTS.values()))
    title = make_title(rng, pools, year)
    uses = pools["title_uses"][title]
    pools["title_uses"][title] = uses + 1
    if uses:                                                     # 撞车时按真实语料的（一）（二）区分
        bare = title.replace("（独占版）", "")
        mark = CN_NUM[uses - 1] if uses <= len(CN_NUM) else str(uses + 1)
        title = f"{bare}（{mark}）" + ("（独占版）" if "独占版" in title else "")
    topic = pools["industry_re"].search(title)
    topic = topic.group(0) if topic else None

    n_industry = rng.choices(range(7), weights=INDUSTRY_COUNT_WEIGHTS, k=1)[0]
    industry: list[str] = []
    if n_industry and topic and rng.random() < 0.8:                # 主体行业通常也在列表里
        industry.append(topic)
    related = pools["co"].get(topic) if topic else None
    while len(industry) < n_industry:
        if related and rng.random() < 0.8:                         # 80% 从共现过的行业里抽
            picked = weighted_choice(rng, related[0], related[1])
        else:
            picked = weighted_choice(rng, pools["industries"], pools["industry_weights"])
        if picked != topic and picked not in industry:
            industry.append(picked)

    day = date(int(year), rng.randint(1, 12), 1) + timedelta(days=rng.randint(0, 27))
    report_id = hashlib.md5(f"{seed}:{i}".encode()).hexdigest()[:24]

    return {"report_id": report_id, "title": title,
            "summary": make_summary(rng, pools, title),
            "industry": industry,
            "layout": weighted_choice(rng, ["横版", "竖版"], LAYOUT_WEIGHTS),
            "publish_date": day.isoformat(),
            "url": f"https://www.leadleo.com/report/reading/{report_id}"}


def _line(name: str, real, gen) -> str:
    return f"{name:<22}{real:>16}{gen:>16}"


def stats(pools: dict, count: int, seed: int) -> None:
    rng = random.Random(seed)
    docs = [make_doc(i, pools, rng, seed) for i in range(count)]
    titles = [d["title"] for d in docs]
    sums = [d["summary"] for d in docs]
    real_t = rng.sample(pools["titles"], min(count, len(pools["titles"])))
    real_s = rng.sample(pools["summaries"], min(count, len(pools["summaries"])))

    def stat(xs, f):
        v = [f(x) for x in xs]
        return f"{statistics.median(v):.0f} / {sorted(v)[int(.9 * len(v))]} / {max(v)}"

    def share(xs, pred):
        return f"{100 * sum(1 for x in xs if pred(x)) / len(xs):.1f}%"

    def toks(xs):
        c = collections.Counter()
        for x in xs:
            c.update(re.findall(r"[\u4e00-\u9fa5]{2,4}", x))
        return c

    print(f"{'真实/生成各 ' + str(count) + ' 篇':<22}{'真实':>16}{'生成':>16}")
    print(_line("title 长度 p50/p90/max", stat(real_t, len), stat(titles, len)))
    print(_line("summary 长度 p50/p90/max", stat(real_s, len), stat(sums, len)))
    print(_line("summary 句号数 p50", f"{statistics.median([s.count('。') for s in real_s]):.0f}",
                f"{statistics.median([s.count('。') for s in sums]):.0f}"))
    print(_line("重复 title", f"{100 * (len(real_t) - len(set(real_t))) / len(real_t):.1f}%",
                f"{100 * (len(titles) - len(set(titles))) / len(titles):.1f}%"))
    print(_line("（独占版）", share(real_t, lambda t: "独占版" in t), share(titles, lambda t: "独占版" in t)))
    print(_line("含 “：”", share(real_t, lambda t: "：" in t), share(titles, lambda t: "：" in t)))
    print(_line("含 “中国”", share(real_t, lambda t: "中国" in t), share(titles, lambda t: "中国" in t)))
    print(_line("summary <50 字", share(real_s, lambda s: len(s) < 50), share(sums, lambda s: len(s) < 50)))
    print(_line("summary 含 《》", share(real_s, lambda s: "《" in s), share(sums, lambda s: "《" in s)))
    print(_line("套话开头", share(real_s, lambda s: s.startswith("沙利文联合头豹研究院谨此发布")),
                share(sums, lambda s: s.startswith("沙利文联合头豹研究院谨此发布"))))
    print(_line("不同 title 词(2-4字)", f"{len(toks(real_t))}", f"{len(toks(titles))}"))
    print(_line("不同 summary 词", f"{len(toks(real_s))}", f"{len(toks(sums))}"))
    print(_line("不同 summary 前 40 字", f"{len({s[:40] for s in real_s})}", f"{len({s[:40] for s in sums})}"))
    print(_line("不同 title 前 6 字", f"{len({t[:6] for t in real_t})}", f"{len({t[:6] for t in titles})}"))
    print(_line("每篇 industry 条数 p50",
                f"{statistics.median(pools['real_industry_counts']):.0f}",
                f"{statistics.median([len(d['industry']) for d in docs]):.0f}"))
    print(_line("industry 为空",
                share(pools["real_industry_counts"], lambda n: n == 0),
                share([len(d["industry"]) for d in docs], lambda n: n == 0)))
    print(_line("横版", share(pools["real_layouts"], lambda x: x == "横版"),
                share([d["layout"] for d in docs], lambda x: x == "横版")))
    print(_line("2022 年占比（年份分布代表）",
                share(pools["real_years"], lambda y: y == "2022"),
                share([d["publish_date"][:4] for d in docs], lambda y: y == "2022")))


def encode_texts(texts: list[str], chunk: int, in_process: bool) -> list[list[float]]:
    if in_process or not ENCODER_URL:
        from embedding.encoder import Encoder

        encoder = Encoder()
        vectors: list[list[float]] = []
        for start in range(0, len(texts), chunk):
            vectors += encoder.encode_passages(texts[start:start + chunk])
        return vectors

    import httpx

    vectors = []
    with httpx.Client(timeout=600.0) as client:
        for start in range(0, len(texts), chunk):
            res = client.post(f"{ENCODER_URL.rstrip('/')}/encode",
                              json={"texts": texts[start:start + chunk], "kind": "passage"})
            res.raise_for_status()
            vectors += res.json()["vectors"]
    return vectors


def ensure_index(es, args) -> None:
    body = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
    settings = dict(body.get("settings") or {})
    settings["number_of_shards"] = args.shards
    settings["number_of_replicas"] = args.replicas
    if args.recreate and es.indices.exists(index=args.index):
        es.indices.delete(index=args.index)
        print(f"  dropped {args.index}")
    if es.indices.exists(index=args.index):
        print(f"  {args.index} 已存在，沿用现有 mapping")
        return
    es.indices.create(index=args.index, settings=settings, mappings=body.get("mappings"))
    print(f"  created {args.index}（{args.shards} 分片 / {args.replicas} 副本）")


def main() -> None:
    ap = argparse.ArgumentParser(description="造 10 万级报告数据并灌进压测索引")
    ap.add_argument("--count", type=int, default=100000)
    ap.add_argument("--index", default="knowledge_report_stress")
    ap.add_argument("--seed", type=int, default=20260101)
    ap.add_argument("--shards", type=int, default=3, help="压测索引分片数（生产 mapping 不动）")
    ap.add_argument("--replicas", type=int, default=0)
    ap.add_argument("--chunk", type=int, default=128, help="编码批量（编码服务上限 256）")
    ap.add_argument("--bulk", type=int, default=500, help="bulk 批量")
    ap.add_argument("--recreate", action="store_true", help="先删后建索引")
    ap.add_argument("--in-process", action="store_true", help="不用编码服务，进程内加载模型")
    ap.add_argument("--stats", type=int, default=0, help="只生成 N 条打印分布对照，不连 ES")
    ap.add_argument("--dry-run", type=int, default=0, help="只生成 N 条打印出来，不连 ES")
    ap.add_argument("--dump", default=None, help="同时把生成结果写文件（不含向量）")
    ap.add_argument("--dump-count", type=int, default=1000)
    args = ap.parse_args()

    reports = load_corpus(SOURCE_PATH)
    pools = build_pools(reports)
    rng = random.Random(args.seed)
    print(f"语料 {len(reports)} 篇：industry {len(pools['industries'])} 个，"
          f"摘要句池 {len(pools['sentences'])} 句，卖点 {len(pools['sells'])} 条")

    if args.stats:
        stats(pools, args.stats, args.seed)
        return

    if args.dry_run:
        for i in range(args.dry_run):
            doc = make_doc(i, pools, rng, args.seed)
            print(json.dumps({**doc, "vector_text": build_text(doc, TYPE)},
                             ensure_ascii=False))
        return

    from elasticsearch import Elasticsearch
    from elasticsearch.helpers import bulk

    from embedding.encoder import resolve_snapshot

    es = Elasticsearch(es_hosts(), basic_auth=es_auth())
    rev = resolve_snapshot().name
    dumped: list[dict] = []

    try:
        ensure_index(es, args)
        started = time.perf_counter()
        done = failed = 0

        for start in range(0, args.count, args.bulk):
            batch = [make_doc(i, pools, rng, args.seed)
                     for i in range(start, min(start + args.bulk, args.count))]
            texts = [build_text(d, TYPE) for d in batch]
            vectors = encode_texts(texts, args.chunk, args.in_process)
            for doc, text, vector in zip(batch, texts, vectors):
                doc["embedding"] = vector
                doc["embed_model"] = MODEL["name"]
                doc["embed_rev"] = rev
                doc["embed_text_hash"] = text_hash(text)
            if args.dump and len(dumped) < args.dump_count:
                dumped += [{k: v for k, v in d.items() if k != "embedding"}
                           for d in batch[:args.dump_count - len(dumped)]]

            ok, errors = bulk(es, ({"_index": args.index, "_id": d["report_id"],
                                    "_source": d} for d in batch),
                              chunk_size=args.bulk, raise_on_error=False, stats_only=False)
            done += ok
            failed += len(errors)
            elapsed = time.perf_counter() - started
            print(f"  {done}/{args.count}  {done / elapsed:.1f} docs/s  "
                  f"失败 {failed}  预计剩余 {(args.count - done) / max(done / elapsed, 1e-9) / 60:.1f} 分钟")
            for e in errors[:3]:
                print(f"    {e}")

        es.indices.refresh(index=args.index)
        print(f"== 完成：{args.index} count={es.count(index=args.index)['count']}，"
              f"失败 {failed}，用时 {(time.perf_counter() - started) / 60:.1f} 分钟 ==")
    finally:
        es.close()

    if args.dump and dumped:
        out = Path(args.dump)
        out.write_text(json.dumps({"reports": dumped}, ensure_ascii=False), encoding="utf-8")
        print(f"样本 {len(dumped)} 条已写入 {out}")


if __name__ == "__main__":
    main()
