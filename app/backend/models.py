"""Stage 1 schema reference for PaperRadar.

This module intentionally keeps plain SQL schema metadata as constants first,
so Stage 1 can move forward before ORM dependencies are installed.
"""

STAGE1_TABLES = [
    "venues",
    "venue_editions",
    "papers",
    "paper_external_ids",
    "paper_files",
    "paper_parse_jobs",
    "paper_metadata_embeddings",
    "subscriptions",
    "subscription_matches",
    "notifications",
]
