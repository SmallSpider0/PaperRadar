from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ChatIntent = Literal["search", "qa", "compare", "summarize", "chat", "meta", "help", "ask_clarification"]
QueryType = Literal["generic", "specific"]
QueryScope = Literal[
    "broad_topic",
    "specific_subtopic",
    "venue_constrained",
    "trend",
    "comparison",
    "unknown",
]
TargetGranularity = Literal["field", "subfield", "method", "task", "benchmark", "application", "unknown"]
ExpectedResultShape = Literal[
    "representative_overview",
    "canonical_papers",
    "newest_papers",
    "specific_technique",
    "unknown",
]
NeighborDriftRisk = Literal["low", "medium", "high"]


class ChatFilters(BaseModel):
    venues: list[str] = Field(default_factory=list)
    years: list[int] = Field(default_factory=list)
    year_from: int | None = None
    year_to: int | None = None


class StructuredQuery(BaseModel):
    intent: ChatIntent = "search"
    topic: str
    query_type: QueryType = "specific"
    topic_labels: list[str] = Field(default_factory=list)
    filters: ChatFilters = Field(default_factory=ChatFilters)
    top_k: int = 8
    needs_fulltext: bool = False
    must_terms: list[str] = Field(default_factory=list)
    should_terms: list[str] = Field(default_factory=list)
    negative_terms: list[str] = Field(default_factory=list)
    translated_query: str | None = None
    translation_english_aliases: list[str] = Field(default_factory=list)
    translation_chinese_aliases: list[str] = Field(default_factory=list)
    translation_canonical_topics: list[str] = Field(default_factory=list)
    translation_prototype_hints: list[str] = Field(default_factory=list)
    translation_language: str | None = None
    translation_confidence: float | None = None
    # Query structure (retrieval policy inputs; not benchmark-driven)
    query_scope: QueryScope = "unknown"
    target_granularity: TargetGranularity = "unknown"
    expected_result_shape: ExpectedResultShape = "unknown"
    risk_of_neighbor_drift: NeighborDriftRisk = "medium"
    profile_id: str | None = None
    prototype_targets: list[str] = Field(default_factory=list)


class ChatSearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=8, ge=1, le=20)


class CitationAnchor(BaseModel):
    label: str
    display_text: str


class RetrievalRelevance(BaseModel):
    score: float
    why_matched: list[str] = Field(default_factory=list)
    raw_signals: dict[str, Any] = Field(default_factory=dict)


class RetrievalPaper(BaseModel):
    paper_id: str | None = None
    title: str
    abstract: str | None = None
    authors_text: str | None = None
    venue_code: str | None = None
    year: int | None = None
    paper_url: str | None = None
    source_pdf_url: str | None = None
    content_policy: str | None = None
    score: float
    match_reasons: list[str] = Field(default_factory=list)
    topic_tags: list[str] = Field(default_factory=list)
    topic_summary: str | None = None
    relevance: RetrievalRelevance | None = None
    citation: CitationAnchor | None = None


class PaperToolResponse(BaseModel):
    tool_name: str = "search_papers"
    query_summary: str
    applied_filters: dict[str, Any] = Field(default_factory=dict)
    results: list[RetrievalPaper] = Field(default_factory=list)


class ChatSearchResponse(BaseModel):
    query: str
    structured_query: StructuredQuery
    results: list[RetrievalPaper]
    retrieval_summary: dict
    paper_tool: PaperToolResponse | None = None


class ChatAnswerRequest(BaseModel):
    query: str
    session_id: str | None = None
    paper_ids: list[str] = Field(default_factory=list)
    top_k: int = Field(default=8, ge=1, le=20)
    context_hint: str | None = None


class Citation(BaseModel):
    id: str | None = None
    label: str | None = None
    paper_id: str | None = None
    title: str
    venue_code: str | None = None
    year: int | None = None
    paper_url: str | None = None
    pdf_url: str | None = None
    score: float
    snippet: str | None = None
    role: str | None = None
    relevance_note: str | None = None
    evidence_type: str = "paper"


class ChatAnswerResponse(BaseModel):
    query: str
    answer: str
    answer_markdown: str | None = None
    citations: list[Citation]
    papers: list[RetrievalPaper]
    structured_query: StructuredQuery
    answer_summary: dict
    used_papers: list[dict[str, Any]] = Field(default_factory=list)
    followup_suggestions: list[str] = Field(default_factory=list)
    compare_result: dict[str, Any] | None = None
    filter_result: dict[str, Any] | None = None


class CandidateFilterRequest(BaseModel):
    candidate_ids: list[str] = Field(default_factory=list)
    instruction: str
    limit: int = Field(default=8, ge=1, le=20)


class CandidateFilterResponse(BaseModel):
    instruction: str
    results: list[RetrievalPaper] = Field(default_factory=list)
    removed_candidates: list[str] = Field(default_factory=list)
    summary: str = ""


class ComparePapersRequest(BaseModel):
    paper_ids: list[str] = Field(default_factory=list)
    compare_dimensions: list[str] = Field(default_factory=list)


class CompareRow(BaseModel):
    paper_id: str | None = None
    title: str
    venue_code: str | None = None
    year: int | None = None
    problem: str | None = None
    approach: str | None = None
    setting: str | None = None
    strengths: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    notable_difference: str | None = None


class ComparePapersResponse(BaseModel):
    paper_ids: list[str] = Field(default_factory=list)
    compare_dimensions: list[str] = Field(default_factory=list)
    rows: list[CompareRow] = Field(default_factory=list)
    summary: str = ""


class ChatMessageRequest(BaseModel):
    query: str
    session_id: str | None = None
    top_k: int = Field(default=8, ge=1, le=20)


class ChatMessageResponse(BaseModel):
    session: dict
    messages: list[dict]
    answer: ChatAnswerResponse
    assistant: dict[str, Any] = Field(default_factory=dict)
    trace: dict[str, Any] = Field(default_factory=dict)


class ChatSessionListResponse(BaseModel):
    sessions: list[dict]


class ChatSessionDetailResponse(BaseModel):
    session: dict
    messages: list[dict]
