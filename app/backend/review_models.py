from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.chat_models import Citation, RetrievalPaper


class ReviewPrepareRequest(BaseModel):
    query: str
    preview_limit: int = Field(default=20, ge=5, le=50)
    candidate_limit: int = Field(default=60, ge=10, le=120)


class ReviewGenerateRequest(BaseModel):
    review_session_id: str
    confirmed: bool = True
    confirmed_paper_ids: list[str] = Field(default_factory=list)


class ReviewSummary(BaseModel):
    review_markdown: str
    included_papers: list[dict[str, Any]] = Field(default_factory=list)
    excluded_papers: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    answer_summary: dict[str, Any] = Field(default_factory=dict)


class ReviewPreparedPayload(BaseModel):
    query: str
    structured_query: dict[str, Any]
    retrieval_summary: dict[str, Any]
    confirmation_prompt: str
    preview_limit: int
    candidate_limit: int
    preview_results: list[RetrievalPaper] = Field(default_factory=list)
    candidate_papers: list[RetrievalPaper] = Field(default_factory=list)
    search_session_payload: dict[str, Any] = Field(default_factory=dict)


class ReviewSessionDetail(BaseModel):
    session: dict[str, Any]
    prepared: ReviewPreparedPayload | None = None
    review: ReviewSummary | None = None
