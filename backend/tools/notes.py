"""
tools/notes.py — SQLite-backed notes store.

This module provides the core notes logic used by BOTH:
  1. The MCP server (mcp_server.py) — which exposes these as MCP tools
  2. Direct imports for testing / CLI use

No @agent.tool decorators here — registration happens in mcp_server.py
via the MCP SDK, and the agent connects via the MCP protocol.
"""

from __future__ import annotations

import sqlite3
import os
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

DB_PATH = os.getenv("NOTES_DB_PATH", "notes.db")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Note(BaseModel):
    id: int
    title: str
    content: str
    tags: list[str]
    created_at: str
    updated_at: str


class SaveNoteResult(BaseModel):
    success: bool
    note_id: Optional[int] = None
    message: str


class SearchNotesResult(BaseModel):
    query: str
    notes: list[Note]
    total: int


# ---------------------------------------------------------------------------
# DB setup
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the notes table if it doesn't exist."""
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT    NOT NULL,
                content    TEXT    NOT NULL,
                tags       TEXT    NOT NULL DEFAULT '',
                created_at TEXT    NOT NULL,
                updated_at TEXT    NOT NULL
            )
        """)
        conn.commit()


# ---------------------------------------------------------------------------
# Core logic (plain functions — no framework dependency)
# ---------------------------------------------------------------------------

def save_note(title: str, content: str, tags: list[str] | None = None) -> SaveNoteResult:
    """
    Save a new note to the database.

    Args:
        title:   Short descriptive title for the note.
        content: Full note body.
        tags:    Optional list of keyword tags for easier retrieval.

    Returns:
        The ID of the newly created note.
    """
    try:
        init_db()
        now = datetime.now().isoformat()
        tags_str = ",".join(tags or [])

        with _get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO notes (title, content, tags, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (title, content, tags_str, now, now),
            )
            conn.commit()
            note_id = cursor.lastrowid

        return SaveNoteResult(
            success=True,
            note_id=note_id,
            message=f"Note '{title}' saved with ID {note_id}.",
        )
    except Exception as e:
        return SaveNoteResult(success=False, message=f"Failed to save note: {str(e)}")


def list_notes(limit: int = 20) -> list[Note]:
    """
    Return the most recent notes, newest first.

    Args:
        limit: Maximum number of notes to return (default 20).

    Returns:
        List of notes ordered by creation date descending.
    """
    init_db()
    limit = min(limit, 50)

    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM notes ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()

    return [
        Note(
            id=row["id"],
            title=row["title"],
            content=row["content"],
            tags=row["tags"].split(",") if row["tags"] else [],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


def search_notes(query: str, limit: int = 10) -> SearchNotesResult:
    """
    Full-text search across note titles, content, and tags.

    Args:
        query: Keyword or phrase to search for.
        limit: Maximum number of results (default 10).

    Returns:
        Matching notes ranked by relevance (SQLite LIKE match).
    """
    init_db()
    limit = min(limit, 20)
    pattern = f"%{query}%"

    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM notes
            WHERE title LIKE ?
               OR content LIKE ?
               OR tags LIKE ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (pattern, pattern, pattern, limit),
        ).fetchall()

    notes = [
        Note(
            id=row["id"],
            title=row["title"],
            content=row["content"],
            tags=row["tags"].split(",") if row["tags"] else [],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]

    return SearchNotesResult(query=query, notes=notes, total=len(notes))


def delete_note(note_id: int) -> dict:
    """
    Delete a note by its ID.

    Args:
        note_id: The integer ID of the note to delete.

    Returns:
        Success status and confirmation message.
    """
    init_db()
    with _get_conn() as conn:
        cursor = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        conn.commit()

    if cursor.rowcount == 0:
        return {"success": False, "message": f"No note found with ID {note_id}."}
    return {"success": True, "message": f"Note {note_id} deleted."}