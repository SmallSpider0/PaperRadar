from __future__ import annotations


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + chunk_size, length)
        chunks.append(text[start:end])
        if end >= length:
            break
        start = max(0, end - overlap)
    return chunks


def chunk_text_with_sections(text: str, chunk_size: int = 1200, overlap: int = 200) -> list[dict]:
    return [
        {
            "chunk_index": index,
            "section": "unknown",
            "text": chunk,
            "retrieval_ready": False,
        }
        for index, chunk in enumerate(chunk_text(text, chunk_size=chunk_size, overlap=overlap))
    ]
