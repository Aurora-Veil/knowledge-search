"""
MCP surface for the OIRF knowledge-graph search API.

"""
from __future__ import annotations

from typing import Annotated, Any, List, Literal, Optional, TypeAlias, Union

from pydantic import BaseModel, ConfigDict, Field

from mcp_types import Tool as MCPTool

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from ..config import COLLECTION_BY_TYPE
from ..routers.search import SearchRequest
from ..search.associations import DEFAULT_LIMIT, MAX_HOPS, MAX_LIMIT
from ..search.associations import neighborhood
from ..search.objects import get_object as get_object_service
from ..search.projects import list_projects as list_projects_service
from ..search.service import search as search_service
from ..search.service_reports import get as get_report_service
from ..search.service_reports import search as search_reports_service

# REVIEW_STATUSES = ("FORMAL", "PENDING", "DISPUTED", "REJECTED")
# CONFIDENCE_LEVELS = ("high", "medium", "low")
# SOURCE_TYPES = ("primary_interview", "secondary_public", "analyst_calculation")
# EVIDENCE_TYPES = ("历史值", "预估值", "计算值", "规则值")
ReviewStatus: TypeAlias = Literal["FORMAL", "PENDING", "DISPUTED", "REJECTED"]
ConfidenceLevel: TypeAlias = Literal["high", "medium", "low"]
SourceType: TypeAlias = Literal["primary_interview", "secondary_public", "analyst_calculation"]
EvidenceType: TypeAlias = Literal["历史值", "预估值", "计算值", "规则值"]
ReportLayout: TypeAlias = Literal["横版", "竖版"]

SERVER_NAME = "oirf-search"

SERVER_INSTRUCTIONS = """

OIRF 知识图谱检索 MCP Server

知识图谱检索工具：
- 全文检索 —— search_knowledge：按检索词与筛选条件查材料，返回卡片
- 取对象全文 —— get_object：取单个对象的完整内容
- 取关联 —— get_associations：取某对象的关联子图，可沿推理链向下追溯与反查

先给命中摘要，再按需展开

报告检索工具（独立索引，与上面的知识图谱无关）：
- 检索 —— search_reports：词法 + 向量融合，返回报告卡片
- 取报告正文 —— get_report：按 report_id 取报告完整内容

报告卡片的 score 是 RRF 融合分，raw_score 是 BM25，knn_score 是向量分，match_source 说明命中来自哪一路

"""

def _strip_titles(node):
    """
    去掉 pydantic 自动生成的 JSON Schema title 注释
    """
    if isinstance(node, dict):
        return {k: _strip_titles(v) for k, v in node.items() if k != "title"}
    if isinstance(node, list):
        return [_strip_titles(v) for v in node]
    return node


class _LeanMCPServer(MCPServer):
    """
    在 list_tools() 出口剥掉 schema 里的 title
    只动 input_schema / output_schema
    """

    async def list_tools(self) -> list[MCPTool]:
        tools = await super().list_tools()
        for t in tools:
            if t.input_schema:
                t.input_schema = _strip_titles(t.input_schema)
            if t.output_schema:
                t.output_schema = _strip_titles(t.output_schema)
        return tools


mcp = _LeanMCPServer(name=SERVER_NAME, instructions=SERVER_INSTRUCTIONS)


# --------------------------------------------------------------------------- #
# response shapes: pydantic models
# --------------------------------------------------------------------------- #
class Card(BaseModel):
    """
    One search hit / graph node.

    """

    model_config = ConfigDict(extra="allow")

    id: Optional[str] = Field(None, description="全局唯一标识")
    object_type: Optional[str] = Field(None, description="source / evidence / viewpoint")
    project_id: Optional[int] = Field(None, description="所属项目")
    oirf_id: Optional[str] = Field(None, description="项目内标识，如 evidence:E001")


class SearchResult(BaseModel):
    """
    Search response.

    """

    model_config = ConfigDict(extra="allow")

    total: int = Field(description="符合条件的总数")
    page: int
    size: int
    hits: list[Card] = Field(description="不含正文")


class AssociationsResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    root: Card = Field(description="起点对象")
    project_id: int
    hops: int = Field(description="回显请求值")
    direction: str = Field(description="回显请求值")
    include: str = Field(description="回显请求值")
    nodes: list[Card] = Field(description="不含 root")
    edges: list[dict[str, Any]] = Field(
        description="同一对节点可有多条"
    )
    truncated: list[str] = Field(description="被截断的桶；空表示未截断")
    missing: list[str] = Field(description="被引用但取不到值")


class ProjectInfo(BaseModel):
    project_id: int
    source: int = Field(description="材料数")
    evidence: int = Field(description="证据数")
    viewpoint: int = Field(description="观点数")


class ProjectList(BaseModel):
    projects: list[ProjectInfo]
    total_objects: int = Field(description="各项目对象数之和")


class ReportCard(BaseModel):
    """
    One report search hit.

    """

    model_config = ConfigDict(extra="allow")

    report_id: Optional[str] = Field(None, description="报告唯一标识，取详情时用")
    title: Optional[str] = Field(None, description="报告标题")
    industry: list[str] = Field(default_factory=list, description="行业分类")
    layout: Optional[str] = Field(None, description="横版 / 竖版")
    publish_date: Optional[str] = Field(None, description="发布日期 YYYY-MM-DD")
    url: Optional[str] = Field(None, description="原文链接")
    score: Optional[float] = Field(None, description="RRF 融合分")


class ReportSearchResult(BaseModel):
    """
    Report search response: no summary in cards.
    """
    model_config = ConfigDict(extra="allow")

    total: int = Field(description="词法分支的命中数，不含向量分支")
    page: int
    size: int
    hits: list[ReportCard] = Field(description="按 RRF 融合分降序，不含摘要正文")


# --------------------------------------------------------------------------- #
# tools
# --------------------------------------------------------------------------- #
@mcp.tool(
    title="搜索知识图谱对象",
    annotations={"readOnlyHint": True, "openWorldHint": False},
)
def search_knowledge(
    q: Annotated[
        Optional[str],
        Field(description=(
            "全文检索词，留空则只做筛选。"
        )),
    ] = None,
    type: Annotated[
        Literal["source", "evidence", "viewpoint", "all"],
        Field(description="搜哪类对象，default all"),
    ] = "all",
    mode: Annotated[
        Literal["or", "and", "phrase"],
        Field(description=(
            "or = 任一词命中；and = 所有词均命中；phrase = 所有词相邻"
        )),
    ] = "or",
    project_id: Annotated[
        Optional[Union[int, List[int]]],
        Field(description=(
            "单项目 = 单个整数，多项目 = 整数数组；不传 = 全部项目"
        )),
    ] = None,
    status: Annotated[
        Optional[ReviewStatus],
        Field(description="精确匹配 identity.status"),
    ] = None,
    presentation_type: Annotated[
        Optional[EvidenceType | SourceType | str],
        Field(description=(
            "精确匹配 presentation.type"
        )),
    ] = None,
    period: Annotated[
        Optional[str],
        Field(description="时期，精确串匹配：2024 匹配不到区间值 2023-2027。只对 evidence 生效"),
    ] = None,
    region: Annotated[
        Optional[str], Field(description="地区，如 全球 / 中国。只对 evidence 生效")] = None,
    industry: Annotated[Optional[str], Field(description="行业。只对 evidence 生效")] = None,
    source_type: Annotated[
        Optional[Union[SourceType, List[SourceType]]],
        Field(description="来源类型。只对 evidence 生效"),
    ] = None,
    publisher: Annotated[
        Optional[Union[str, List[str]]],
        Field(description=(
            "来源方，只约束 source/evidence"
        )),
    ] = None,
    confidence_level: Annotated[
        Optional[ConfidenceLevel],
        Field(description="置信度。只对 source / evidence 生效"),
    ] = None,
    claim_type: Annotated[
        Optional[str],
        Field(description="判断类型，如 事实判断 / 趋势判断。只对 viewpoint 生效"),
    ] = None,
    applicable_scenario: Annotated[
        Optional[str], Field(description="适用场景。只对 viewpoint 生效")] = None,
    cross_validation_mode: Annotated[
        Optional[str], Field(description="交叉验证方式。只对 viewpoint 生效")] = None,
    responsible_role: Annotated[
        Optional[str],
        Field(description="职责角色，匹配 responsibility[].operator.role，如 analyst"),
    ] = None,
    source_ids: Annotated[
        Optional[List[str]],
        Field(description=(
            "引用 source 溯源,对 source 不适用"
        )),
    ] = None,
    evidence_ids: Annotated[
        Optional[List[str]],
        Field(description="引用 evidence 溯源，只对 viewpoint 生效"),
    ] = None,
    page: Annotated[int, Field(ge=1, description="page")] = 1,
    size: Annotated[int, Field(ge=1, le=100, description="size per page")] = 20,
    highlight: Annotated[bool, Field(description="ensure <em> <em> highlight tags")] = True,
) -> SearchResult:
    """按检索词与筛选条件查材料，返回卡片"""
    params = SearchRequest(
        q=q, type=type, mode=mode, project_id=project_id, status=status,
        presentation_type=presentation_type, period=period, region=region,
        industry=industry, source_type=source_type, publisher=publisher,
        confidence_level=confidence_level, claim_type=claim_type,
        applicable_scenario=applicable_scenario,
        cross_validation_mode=cross_validation_mode,
        responsible_role=responsible_role, source_ids=source_ids,
        evidence_ids=evidence_ids, page=page, size=size, highlight=highlight,
    ).model_dump(exclude_none=True)
    try:
        result = search_service(params)
        if result.get("hits"):
            return SearchResult(**result)
        return SearchResult(**result, notice=(
            """
            没有命中。

            以下筛选只约束特定类型：
            - evidence 专属 period/region/industry/source_type
            - viewpoint 专属 claim_type/applicable_scenario/cross_validation_mode/evidence_ids
            - source 与 evidence 共用 confidence_level/publisher
            - evidence 与 viewpoint 共用 source_ids

            去筛选、改 type、或试调整 mode 与更短的 q。
            """
            
        ))
    except ToolError:
        raise
    except Exception as exc:  # noqa: BLE001 - surfaced to the model verbatim
        raise ToolError(f"Search Fail:{type(exc).__name__}: {exc}") from exc


@mcp.tool(
    title="取完整对象",
    annotations={"readOnlyHint": True, "openWorldHint": False},
)
def get_object(
    object_type: Literal["source", "evidence", "viewpoint"],
    oirf_id: Annotated[str, Field(description="如 viewpoint:V001")],
    project_id: int,
) -> dict[str, Any]:
    """
    按类型 + oirf_id + project_id 取完整对象字段

    - object_type 必须是 source / evidence / viewpoint 之一。
    - oirf_id 形如 viewpoint:V001，前缀必须与 object_type 一致。
    - project_id 必填
    """
    if object_type not in COLLECTION_BY_TYPE:
        raise ToolError(
            f"unknown object_type: {object_type!r} (expected one of {list(COLLECTION_BY_TYPE)})"
        )
    prefix = oirf_id.split(":", 1)[0]
    if prefix != object_type:
        raise ToolError(
            f"oirf_id 前缀与 object_type 不一致：oirf_id={oirf_id!r} 对应 "
            f"{prefix!r}，但 object_type={object_type!r}"
        )

    try:
        obj = get_object_service(object_type, oirf_id, project_id)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"取全字段失败：{type(exc).__name__}: {exc}") from exc

    if obj is None:
        raise ToolError(
            f"在 project_id={project_id} 中找不到 {object_type} {oirf_id!r}"
            f"请确认 project_id 是否正确"
            f"以及 oirf_id 与 project_id 是否来自同一条搜索结果"
        )
    return obj


@mcp.tool(
    title="取关联子图",
    annotations={"readOnlyHint": True, "openWorldHint": False},
)
def get_associations(
    object_type: Literal["source", "evidence", "viewpoint"],
    oirf_id: Annotated[str, Field(description="如 viewpoint:V001")],
    project_id: int,
    hops: Annotated[int, Field(ge=1, le=MAX_HOPS, description="跳数，1 或 2")] = 1,
    direction: Annotated[
        Literal["out", "in", "both"],
        Field(description="out = 观点→证据→材料；in = 谁引用了它；both = 两者"),
    ] = "both",
    types: Annotated[
        Optional[list[Literal["source", "evidence", "viewpoint"]]],
        Field(description="只保留这些节点类型；不影响展开"),
    ] = None,
    include: Annotated[
        Literal["card", "ref"],
        Field(description="card -> 完整卡片，ref -> id/oirf_id/object_type/project_id/identity"),
    ] = "card",
    limit: Annotated[
        int,
        Field(ge=1, le=MAX_LIMIT, description="每个 (direction, type) 桶的上限，最大 200"),
    ] = DEFAULT_LIMIT,
) -> AssociationsResult:
    """
    取从一个对象出发的关联子图，返回 root / nodes / edges
    edges[].label 是每一步的推理文本，解释证据如何支撑结论
    
    """
    if oirf_id.split(":", 1)[0] != object_type:
        raise ToolError(
            f"oirf_id 前缀与 object_type 不一致：oirf_id={oirf_id!r}，object_type={object_type!r}"
        )

    types_set = set(types) if types else None
    try:
        result = neighborhood(
            object_type=object_type,
            oirf_id=oirf_id,
            project_id=project_id,
            hops=hops,
            direction=direction,
            types=types_set,
            include=include,
            limit=limit,
        )
        if result is None:
            raise ToolError(
                f"在 project_id={project_id} 中找不到 {object_type} {oirf_id!r}，"
                f"无法展开关联子图。请确认 project_id 与 oirf_id。"
            )
        return AssociationsResult(**result)
    except ToolError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"取关联子图失败：{type(exc).__name__}: {exc}") from exc


@mcp.tool(
    title="列出项目",
    annotations={"readOnlyHint": True, "openWorldHint": False},
)
def list_projects() -> ProjectList:
    """
    列出库里有哪些 project_id，以及每个项目的对象数量。
    """
    try:
        return ProjectList(**list_projects_service())
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"查询项目列表失败：{type(exc).__name__}: {exc}") from exc


@mcp.tool(
    title="检索报告",
    annotations={"readOnlyHint": True, "openWorldHint": False},
)
def search_reports(
    q: Annotated[
        str,
        Field(description="检索词"),
    ],
    mode: Annotated[
        Literal["or", "and", "phrase"],
        Field(description=(
            "or = 任一词命中；and = 所有词均命中；phrase = 所有词相邻"
        )),
    ] = "or",
    layout: Annotated[
        Optional[ReportLayout],
        Field(description="版式"),
    ] = None,
    industry: Annotated[
        Optional[List[str]],
        Field(description="行业分类，精确匹配，可多值"),
    ] = None,
    publish_date_from: Annotated[
        Optional[str],
        Field(description="起始发布日期，YYYY-MM-DD"),
    ] = None,
    publish_date_to: Annotated[
        Optional[str],
        Field(description="截止发布日期，YYYY-MM-DD"),
    ] = None,
    page: Annotated[int, Field(ge=1, description="page")] = 1,
    size: Annotated[int, Field(ge=1, le=100, description="size per page")] = 20,
) -> ReportSearchResult:
    """按检索词查报告，返回标题等卡片信息，不含摘要正文"""
    params: dict[str, Any] = {
        "q": q,
        "mode": mode,
        "layout": layout,
        "industry": industry,
        "publish_date_from": publish_date_from,
        "publish_date_to": publish_date_to,
        "page": page,
        "size": size,
    }
    params = {k: v for k, v in params.items() if v is not None}

    try:
        result = search_reports_service(params)
        if result.get("hits"):
            return ReportSearchResult(**result)
        return ReportSearchResult(**result, notice=(
            """
            没有命中。

            报告检索是词法 + 向量两路召回后融合的：
            - mode=and/phrase 会收紧词法分支，先退回 or 或换更短的 q
            - layout / industry / 日期都是精确匹配，值不匹配会直接过滤空
            - industry keyword 为完整行业名，可先不带过滤检索，再照结果里的值筛

            去筛选、换更短的 q、或只留核心词重试。
            """
        ))
    except ToolError:
        raise
    except Exception as exc:  # noqa: BLE001 - surfaced to the model verbatim
        raise ToolError(f"报告检索失败：{type(exc).__name__}: {exc}") from exc


@mcp.tool(
    title="取报告详情",
    annotations={"readOnlyHint": True, "openWorldHint": False},
)
def get_report(
    report_id: Annotated[
        str,
        Field(description="report_id"),
    ],
) -> dict[str, Any]:
    """按 report_id 取报告完整内容"""
    try:
        report = get_report_service(report_id)
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"取报告详情失败：{type(exc).__name__}: {exc}") from exc

    if report is None:
        raise ToolError(
            f"找不到 report_id={report_id!r}，请确认 report_id "
        )
    return report


__all__ = ["mcp", "SERVER_NAME"]
