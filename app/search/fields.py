from __future__ import annotations

# full text search weights, grouped by type
WEIGHTS: dict[str, list[str]] = {
    "source": ["identity.name^3", "presentation.title^2", "presentation.publisher.text^2"],
    "evidence": ["identity.name^3", "presentation.subject.text^2", 
                 "presentation.indicator^2", "presentation.value^2", "experience.original_publish.text^2"],
    "viewpoint": ["presentation.name^3", "identity.name^2.5", "experience.name^2"],
}

# _source whitelist -> long text should be fetched from Mongo
# full text -> .text (subject.text/publisher.text)
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

# publisher field for each type
PUBLISHER_FIELD: dict[str, str] = {
    "source": "presentation.publisher",
    "evidence": "experience.original_publish",
}

# association term
ASSOC_SOURCE_IDS_TYPES = ("evidence", "viewpoint")
ASSOC_EVIDENCE_IDS_TYPES = ("viewpoint",)

# experience.confidence_level exists only in source/evidence
# viewpoint's experience layer uses cross_validation_mode - a term on a missing field is a silent 0 hits
CONFIDENCE_LEVEL_TYPES = ("source", "evidence")

__all__ = ["WEIGHTS", "SOURCE_BY_TYPE", "ASSOC_SOURCE_IDS_TYPES", "ASSOC_EVIDENCE_IDS_TYPES",
           "CONFIDENCE_LEVEL_TYPES", "PUBLISHER_FIELD"]
