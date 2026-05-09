#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
GENERATED_DIR = BASE_DIR / 'data' / 'generated'

MOJIBAKE_REPLACEMENTS = {
    'â': "'",
    'â': "'",
    'â': '"',
    'â': '"',
    'â': '-',
    'â': '-',
    'Ã': 'É',
    'Ã©': 'é',
    'â€™': "'",
    'â€œ': '"',
    'â€': '"',
    'â€': '"',
}


def fix_mojibake(text: str) -> str:
    out = text or ''
    for bad, good in MOJIBAKE_REPLACEMENTS.items():
        out = out.replace(bad, good)
    return out


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = fix_mojibake(str(value))
    text = html.unescape(text)
    text = re.sub(r'</?(jats:)?[^>]+>', ' ', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = text.replace('\xa0', ' ')
    text = text.replace('``', '"').replace("''", '"')
    text = text.replace('textit{', '').replace('textbf{', '').replace('emph{', '')
    text = text.replace('\\varepsilon', 'ε').replace('\\delta', 'δ').replace('\\Theta', 'Θ')
    text = text.replace('\\left', '').replace('\\right', '')
    text = re.sub(r'\\[a-zA-Z]+', ' ', text)
    text = text.replace('{', '').replace('}', '')
    text = text.replace('$', '')
    text = re.sub(r'\s+', ' ', text).strip()
    return text or None


def clean_record(record: dict) -> dict:
    for key in ['title', 'abstract', 'authors_text', 'paper_url', 'source_pdf_url', 'source', 'content_policy']:
        if key in record:
            record[key] = clean_text(record.get(key))
    return record


def main() -> None:
    for path in sorted(GENERATED_DIR.glob('*_normalized.json')):
        rows = json.loads(path.read_text(encoding='utf-8'))
        cleaned = [clean_record(dict(row)) for row in rows]
        path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding='utf-8')
        html_residue = sum(1 for r in cleaned if '<' in (r.get('abstract') or '') or '&' in (r.get('abstract') or ''))
        print(f'cleaned {path.name}: {len(cleaned)} rows, html_residue={html_residue}')


if __name__ == '__main__':
    main()
