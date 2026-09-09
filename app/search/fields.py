"""搜索领域的可调参数（数据驱动），集中一处便于对真实数据校准。

- `WEIGHTS`：各类型全文检索字段（field^boost），进 multi_match。权重只影响排序、不影响召回。
- `SOURCE_BY_TYPE`：命中卡片需带回的 `_source` 字段白名单。只含可搜/可筛字段 + 识别键；
  纯展示长文本（raw_texts/notes/summary/content/explanation/narrative/*_reason/lifecycle）由 /objects 回 Mongo 取。

两者将来若要按数据调参（§6 权重校准），只改这个文件。
"""
from __future__ import annotations

# 各类型全文检索字段（field^boost）。
WEIGHTS: dict[str, list[str]] = {
    "source": [
        "identity.name^3",
        "presentation.title^2",
        "presentation.publisher.text^2",
    ],
    "evidence": [
        "identity.name^3",
        "presentation.subject.text^2",
        "presentation.indicator^2",
        "presentation.value^2",
    ],
    "viewpoint": [
        "presentation.name^3",
        "identity.name^2.5",
        "experience.name^2",
    ],
}

# 命中卡片需带回的 `_source` 字段（公共 + 各类型）。
# 注意：全文检索若用到 `.text` 子字段（subject.text/publisher.text），必须带对应基字段
# （presentation.subject/presentation.publisher），否则 highlight 无从取原文。
_SOURCE_COMMON = [
    "id",
    "project_id",
    "oirf_id",
    "identity.name",
    "identity.object_type",
    "identity.status",
]

SOURCE_BY_TYPE: dict[str, list[str]] = {
    "source": _SOURCE_COMMON
    + [
        "presentation.type",
        "presentation.title",
        "presentation.uri",
        "presentation.publisher",
        "presentation.rights",
        "experience.level",
        "experience.label",
        "experience.confidence_level",
        "responsibility",
    ],
    "evidence": _SOURCE_COMMON
    + [
        "presentation.subject",
        "presentation.type",
        "presentation.source_type",
        "presentation.industry",
        "presentation.indicator",
        "presentation.value",
        "presentation.period",
        "presentation.region",
        "presentation.unit",
        "reasoning.source_ids",
        "experience.confidence_level",
        "experience.original_publish",
        "responsibility",
    ],
    "viewpoint": _SOURCE_COMMON
    + [
        "presentation.name",
        "presentation.type",
        "experience.name",
        "experience.applicable_scenario",
        "experience.claim_type",
        "experience.cross_validation_mode",
        "reasoning.steps",
        "responsibility",
    ],
}

__all__ = ["WEIGHTS", "SOURCE_BY_TYPE"]
