"""Brainstorm comment database operations — per-section annotations on brainstorm pages."""

import logging
from typing import List, Dict, Optional
from utilities.postgres.core import db_cursor, _fetchall

logger = logging.getLogger(__name__)
_schema_ensured = False


def ensure_brainstorm_comments_table():
    """Create brainstorm_comments table if it doesn't exist (lazy, once per process)."""
    global _schema_ensured
    if _schema_ensured:
        return
    _schema_ensured = True
    with db_cursor(commit=True) as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pilgrim.brainstorm_comments (
                id SERIAL PRIMARY KEY,
                page_key TEXT NOT NULL,
                section_idx INTEGER NOT NULL,
                author_name TEXT NOT NULL,
                author_type TEXT DEFAULT 'anon',
                comment_text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_bc_page
            ON pilgrim.brainstorm_comments(page_key)
        """)


def get_comments_for_page(page_key: str) -> List[Dict]:
    """Return all comments for a brainstorm page, ordered by section then time."""
    ensure_brainstorm_comments_table()
    with db_cursor() as cur:
        cur.execute("""
            SELECT id, section_idx, author_name, author_type, comment_text, created_at
            FROM pilgrim.brainstorm_comments
            WHERE page_key = %s
            ORDER BY section_idx, created_at ASC
        """, (page_key,))
        return _fetchall(cur)


def add_comment(page_key: str, section_idx: int, author_name: str,
                author_type: str, comment_text: str) -> Optional[Dict]:
    """Insert a comment and return it."""
    ensure_brainstorm_comments_table()
    with db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO pilgrim.brainstorm_comments
                (page_key, section_idx, author_name, author_type, comment_text)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, section_idx, author_name, author_type, comment_text, created_at
        """, (page_key, section_idx, author_name, author_type, comment_text))
        row = cur.fetchone()
        return dict(row) if row else None
