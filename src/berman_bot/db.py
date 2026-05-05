"""SQLite storage layer for chapters, paragraphs, and problems.

The schema mirrors the structure on amkbook.net:

  Book → Chapter → Paragraph → Problem

A `Problem` belongs to exactly one paragraph and has a Berman number
(the canonical problem number in the book) plus an optional internal
amkbook id (used to fetch the source page).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS chapters (
    id          INTEGER PRIMARY KEY,
    number      INTEGER NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    range_text  TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS paragraphs (
    id          INTEGER PRIMARY KEY,
    chapter_id  INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    number      INTEGER NOT NULL,
    title       TEXT NOT NULL,
    range_text  TEXT NOT NULL DEFAULT '',
    UNIQUE(chapter_id, number)
);

CREATE TABLE IF NOT EXISTS problems (
    id              INTEGER PRIMARY KEY,
    berman_number   INTEGER NOT NULL UNIQUE,
    paragraph_id    INTEGER NOT NULL REFERENCES paragraphs(id) ON DELETE CASCADE,
    amk_internal_id INTEGER,
    source_url      TEXT,
    statement_html  TEXT,
    solution_html   TEXT,
    answer_html     TEXT,
    image_path      TEXT,
    telegram_file_id TEXT,
    has_solution    INTEGER NOT NULL DEFAULT 0,
    user_added      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_problems_paragraph ON problems(paragraph_id);
CREATE INDEX IF NOT EXISTS idx_problems_berman ON problems(berman_number);

CREATE TABLE IF NOT EXISTS user_stats (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    first_seen  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    requests    INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass
class Chapter:
    id: int
    number: int
    title: str
    range_text: str


@dataclass
class Paragraph:
    id: int
    chapter_id: int
    number: int
    title: str
    range_text: str


@dataclass
class Problem:
    id: int
    berman_number: int
    paragraph_id: int
    amk_internal_id: int | None
    source_url: str | None
    statement_html: str | None
    solution_html: str | None
    answer_html: str | None
    image_path: str | None
    telegram_file_id: str | None
    has_solution: bool
    user_added: bool


def _row_to_chapter(row: sqlite3.Row) -> Chapter:
    return Chapter(
        id=row["id"],
        number=row["number"],
        title=row["title"],
        range_text=row["range_text"],
    )


def _row_to_paragraph(row: sqlite3.Row) -> Paragraph:
    return Paragraph(
        id=row["id"],
        chapter_id=row["chapter_id"],
        number=row["number"],
        title=row["title"],
        range_text=row["range_text"],
    )


def _row_to_problem(row: sqlite3.Row) -> Problem:
    return Problem(
        id=row["id"],
        berman_number=row["berman_number"],
        paragraph_id=row["paragraph_id"],
        amk_internal_id=row["amk_internal_id"],
        source_url=row["source_url"],
        statement_html=row["statement_html"],
        solution_html=row["solution_html"],
        answer_html=row["answer_html"],
        image_path=row["image_path"],
        telegram_file_id=row["telegram_file_id"],
        has_solution=bool(row["has_solution"]),
        user_added=bool(row["user_added"]),
    )


class Database:
    """Thin wrapper over sqlite3 with helper queries used by the bot and tools."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._conn.execute("PRAGMA journal_mode = WAL;")
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self):
        try:
            self._conn.execute("BEGIN")
            yield self._conn
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    # --- Chapters -------------------------------------------------------

    def upsert_chapter(self, number: int, title: str, range_text: str = "") -> int:
        cur = self._conn.execute(
            """
            INSERT INTO chapters(number, title, range_text)
            VALUES (?, ?, ?)
            ON CONFLICT(number) DO UPDATE SET
                title = excluded.title,
                range_text = excluded.range_text
            RETURNING id
            """,
            (number, title, range_text),
        )
        row = cur.fetchone()
        return int(row[0])

    def list_chapters(self) -> list[Chapter]:
        cur = self._conn.execute("SELECT * FROM chapters ORDER BY number")
        return [_row_to_chapter(r) for r in cur.fetchall()]

    def get_chapter(self, chapter_id: int) -> Chapter | None:
        cur = self._conn.execute("SELECT * FROM chapters WHERE id = ?", (chapter_id,))
        row = cur.fetchone()
        return _row_to_chapter(row) if row else None

    # --- Paragraphs -----------------------------------------------------

    def upsert_paragraph(
        self, chapter_id: int, number: int, title: str, range_text: str = ""
    ) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO paragraphs(chapter_id, number, title, range_text)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chapter_id, number) DO UPDATE SET
                title = excluded.title,
                range_text = excluded.range_text
            RETURNING id
            """,
            (chapter_id, number, title, range_text),
        )
        row = cur.fetchone()
        return int(row[0])

    def list_paragraphs(self, chapter_id: int) -> list[Paragraph]:
        cur = self._conn.execute(
            "SELECT * FROM paragraphs WHERE chapter_id = ? ORDER BY number",
            (chapter_id,),
        )
        return [_row_to_paragraph(r) for r in cur.fetchall()]

    def get_paragraph(self, paragraph_id: int) -> Paragraph | None:
        cur = self._conn.execute("SELECT * FROM paragraphs WHERE id = ?", (paragraph_id,))
        row = cur.fetchone()
        return _row_to_paragraph(row) if row else None

    # --- Problems -------------------------------------------------------

    def upsert_problem(
        self,
        berman_number: int,
        paragraph_id: int,
        amk_internal_id: int | None = None,
        source_url: str | None = None,
        statement_html: str | None = None,
        solution_html: str | None = None,
        answer_html: str | None = None,
        image_path: str | None = None,
        telegram_file_id: str | None = None,
        has_solution: bool | None = None,
        user_added: bool = False,
    ) -> int:
        if has_solution is None:
            has_solution = bool(solution_html and solution_html.strip())

        cur = self._conn.execute(
            """
            INSERT INTO problems (
                berman_number, paragraph_id, amk_internal_id, source_url,
                statement_html, solution_html, answer_html,
                image_path, telegram_file_id, has_solution, user_added
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(berman_number) DO UPDATE SET
                paragraph_id = excluded.paragraph_id,
                amk_internal_id = COALESCE(excluded.amk_internal_id, problems.amk_internal_id),
                source_url = COALESCE(excluded.source_url, problems.source_url),
                statement_html = COALESCE(excluded.statement_html, problems.statement_html),
                solution_html = COALESCE(excluded.solution_html, problems.solution_html),
                answer_html = COALESCE(excluded.answer_html, problems.answer_html),
                image_path = COALESCE(excluded.image_path, problems.image_path),
                telegram_file_id = COALESCE(excluded.telegram_file_id, problems.telegram_file_id),
                has_solution = excluded.has_solution OR problems.has_solution,
                user_added = excluded.user_added OR problems.user_added,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id
            """,
            (
                berman_number,
                paragraph_id,
                amk_internal_id,
                source_url,
                statement_html,
                solution_html,
                answer_html,
                image_path,
                telegram_file_id,
                int(has_solution),
                int(user_added),
            ),
        )
        row = cur.fetchone()
        return int(row[0])

    def get_problem_by_berman_number(self, berman_number: int) -> Problem | None:
        cur = self._conn.execute(
            "SELECT * FROM problems WHERE berman_number = ?",
            (berman_number,),
        )
        row = cur.fetchone()
        return _row_to_problem(row) if row else None

    def list_problems(self, paragraph_id: int) -> list[Problem]:
        cur = self._conn.execute(
            "SELECT * FROM problems WHERE paragraph_id = ? ORDER BY berman_number",
            (paragraph_id,),
        )
        return [_row_to_problem(r) for r in cur.fetchall()]

    def update_telegram_file_id(self, problem_id: int, file_id: str) -> None:
        self._conn.execute(
            "UPDATE problems SET telegram_file_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (file_id, problem_id),
        )

    def update_image_path(self, problem_id: int, image_path: str) -> None:
        self._conn.execute(
            "UPDATE problems SET image_path = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (image_path, problem_id),
        )

    def update_problem_html(
        self,
        berman_number: int,
        statement_html: str | None,
        solution_html: str | None,
        answer_html: str | None,
    ) -> None:
        has_solution = bool(solution_html and solution_html.strip())
        self._conn.execute(
            """
            UPDATE problems SET
                statement_html = COALESCE(?, statement_html),
                solution_html  = COALESCE(?, solution_html),
                answer_html    = COALESCE(?, answer_html),
                has_solution   = MAX(has_solution, ?),
                updated_at     = CURRENT_TIMESTAMP
            WHERE berman_number = ?
            """,
            (statement_html, solution_html, answer_html, int(has_solution), berman_number),
        )

    def problems_needing_detail(self) -> list[tuple[int, int]]:
        """Return (berman_number, amk_internal_id) for problems missing detail."""
        cur = self._conn.execute(
            """
            SELECT berman_number, amk_internal_id
            FROM problems
            WHERE amk_internal_id IS NOT NULL
              AND (statement_html IS NULL OR solution_html IS NULL)
            ORDER BY berman_number
            """
        )
        return [(int(r["berman_number"]), int(r["amk_internal_id"])) for r in cur.fetchall()]

    def problems_without_image(self, include_statement_only: bool = False) -> Iterable[Problem]:
        if include_statement_only:
            where = (
                "(has_solution = 1 OR (statement_html IS NOT NULL AND statement_html != '')) "
                "AND (image_path IS NULL OR image_path = '')"
            )
        else:
            where = "has_solution = 1 AND (image_path IS NULL OR image_path = '')"
        cur = self._conn.execute(
            f"SELECT * FROM problems WHERE {where} ORDER BY berman_number"
        )
        return (_row_to_problem(r) for r in cur.fetchall())

    # --- Stats ----------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        cur = self._conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM chapters) AS chapters,
                (SELECT COUNT(*) FROM paragraphs) AS paragraphs,
                (SELECT COUNT(*) FROM problems) AS problems_total,
                (SELECT COUNT(*) FROM problems WHERE has_solution = 1) AS problems_with_solution,
                (SELECT COUNT(*) FROM problems WHERE image_path IS NOT NULL AND image_path != '') AS problems_with_image
            """
        )
        row = cur.fetchone()
        return dict(row)

    def touch_user(self, user_id: int, username: str | None) -> None:
        self._conn.execute(
            """
            INSERT INTO user_stats(user_id, username)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = COALESCE(excluded.username, user_stats.username),
                last_seen = CURRENT_TIMESTAMP,
                requests = user_stats.requests + 1
            """,
            (user_id, username),
        )
