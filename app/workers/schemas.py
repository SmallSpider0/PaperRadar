from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class PaperRecord:
    source: str
    venue_code: str
    year: int
    title: str
    paper_url: str
    abstract: Optional[str] = None
    authors_text: Optional[str] = None
    source_pdf_url: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)
