from __future__ import annotations

# 全文检索字段（field^boost）：权重只影响排序、不影响召回。调参只改这里。
WEIGHTS: dict[str, list[str]] = {
    "source": ["identity.name^3", "presentation.title^2", "presentation.publisher.text^2"],
    "evidence": ["identity.name^3", "presentation.subject.text^2", "presentation.indicator^2", "presentation.value^2"],
    "viewpoint": ["presentation.name^3", "identity.name^2.5", "experience.name^2"],
}

# 命中卡片要带回的 _source 白名单：只含可搜/可筛字段 + 识别键；长文本回 Mongo 取。
# 全文用 `.text` 子字段（subject.text/publisher.text）时须带基字段（presentation.subject/publisher），高亮才能取原文。
_SOURCE_COMMON = ["id", "project_id", "oirf_id", "identity.name", "identity.object_type", "identity.status"]

SOURCE_BY_TYPE: dict[str, list[str]] = {
    "source": _SOURCE_COMMON
    + ["presentation.type", "presentation.title", "presentation.uri", "presentation.publisher", "presentation.rights",
       "experience.level", "experience.label", "experience.confidence_level", "responsibility"],
    "evidence": _SOURCE_COMMON
    + ["presentation.subject", "presentation.type", "presentation.source_type", "presentation.industry",
       "presentation.indicator", "presentation.value", "presentation.period", "presentation.region", "presentation.unit",
       "reasoning.source_ids", "experience.confidence_level", "experience.original_publish", "responsibility"],
    "viewpoint": _SOURCE_COMMON
    + ["presentation.name", "presentation.type", "experience.name", "experience.applicable_scenario",
       "experience.claim_type", "experience.cross_validation_mode", "reasoning.steps", "responsibility"],
}

# 关联（引用溯源）参数只对"能建立该引用"的类型有效。source 是根、不引用材料；evidence 不引用证据。
ASSOC_SOURCE_IDS_TYPES = ("evidence", "viewpoint")
ASSOC_EVIDENCE_IDS_TYPES = ("viewpoint",)

__all__ = ["WEIGHTS", "SOURCE_BY_TYPE", "ASSOC_SOURCE_IDS_TYPES", "ASSOC_EVIDENCE_IDS_TYPES"]
