"""Domain/flow layer for habit tracker operations.

This module contains the single canonical code-paths for:
- Habit CRUD
- Completion log operations
- Stats computation

Routes should call this layer (flows), not hand-roll SQL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import sqlite3

from src.api.db import execute, fetch_all, fetch_one


def _bool_to_int(v: bool) -> int:
    return 1 if v else 0


def _int_to_bool(v: Any) -> bool:
    try:
        return int(v) == 1
    except Exception:
        return bool(v)


def _parse_date_str(d: str) -> date:
    return date.fromisoformat(d)


@dataclass(frozen=True)
class HabitService:
    """Reusable flow/service entrypoint for habit tracker DB operations.

    Contract:
    - Inputs: sqlite3.Connection
    - Outputs: dicts matching DB rows (converted where needed)
    - Errors: raises ValueError for not-found; sqlite3.Error bubbles up
    """

    conn: sqlite3.Connection

    # ---- Habits CRUD ----
    def list_habits(self, include_archived: bool) -> List[Dict[str, Any]]:
        sql = """
        SELECT id, name, description, color_hex, icon_name, is_archived, created_at, updated_at
        FROM habits
        WHERE (? = 1) OR (is_archived = 0)
        ORDER BY is_archived ASC, id DESC
        """
        rows = fetch_all(self.conn, sql, (_bool_to_int(include_archived),))
        for r in rows:
            r["is_archived"] = _int_to_bool(r["is_archived"])
        return rows

    def get_habit(self, habit_id: int) -> Dict[str, Any]:
        row = fetch_one(
            self.conn,
            """
            SELECT id, name, description, color_hex, icon_name, is_archived, created_at, updated_at
            FROM habits WHERE id = ?
            """,
            (habit_id,),
        )
        if not row:
            raise ValueError("habit_not_found")
        row["is_archived"] = _int_to_bool(row["is_archived"])
        return row

    def create_habit(self, data: Dict[str, Any]) -> Dict[str, Any]:
        habit_id = execute(
            self.conn,
            """
            INSERT INTO habits (name, description, color_hex, icon_name, is_archived)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                data["name"],
                data.get("description"),
                data.get("color_hex"),
                data.get("icon_name"),
                _bool_to_int(bool(data.get("is_archived", False))),
            ),
        )
        return self.get_habit(habit_id)

    def update_habit(self, habit_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        existing = self.get_habit(habit_id)
        merged = {
            "name": data.get("name", existing["name"]),
            "description": data.get("description", existing.get("description")),
            "color_hex": data.get("color_hex", existing.get("color_hex")),
            "icon_name": data.get("icon_name", existing.get("icon_name")),
            "is_archived": data.get("is_archived", existing.get("is_archived", False)),
        }
        execute(
            self.conn,
            """
            UPDATE habits
            SET name = ?, description = ?, color_hex = ?, icon_name = ?, is_archived = ?
            WHERE id = ?
            """,
            (
                merged["name"],
                merged["description"],
                merged["color_hex"],
                merged["icon_name"],
                _bool_to_int(bool(merged["is_archived"])),
                habit_id,
            ),
        )
        return self.get_habit(habit_id)

    def delete_habit(self, habit_id: int) -> None:
        # Ensure it exists for consistent 404 behavior.
        _ = self.get_habit(habit_id)
        execute(self.conn, "DELETE FROM habits WHERE id = ?", (habit_id,))

    # ---- Completion logs ----
    def log_completion(self, habit_id: int, habit_date: date, note: Optional[str], mood: Optional[int]) -> Dict[str, Any]:
        # Ensure habit exists early
        _ = self.get_habit(habit_id)

        # Enforce uniqueness per (habit_id, habit_date) via INSERT OR REPLACE:
        # - If already exists, we overwrite note/mood and keep completed_at updated.
        execute(
            self.conn,
            """
            INSERT INTO habit_logs (habit_id, habit_date, completed_at, note, mood)
            VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?)
            ON CONFLICT(habit_id, habit_date) DO UPDATE SET
                completed_at = CURRENT_TIMESTAMP,
                note = excluded.note,
                mood = excluded.mood
            """,
            (habit_id, habit_date.isoformat(), note, mood),
        )
        row = fetch_one(
            self.conn,
            """
            SELECT id, habit_id, habit_date, completed_at, note, mood, created_at
            FROM habit_logs
            WHERE habit_id = ? AND habit_date = ?
            """,
            (habit_id, habit_date.isoformat()),
        )
        if not row:
            raise RuntimeError("Failed to create/read completion log after write.")
        return row

    def unlog_completion(self, habit_id: int, habit_date: date) -> None:
        _ = self.get_habit(habit_id)
        execute(
            self.conn,
            "DELETE FROM habit_logs WHERE habit_id = ? AND habit_date = ?",
            (habit_id, habit_date.isoformat()),
        )

    def list_completions(self, habit_id: int, from_date: date, to_date: date) -> List[Dict[str, Any]]:
        _ = self.get_habit(habit_id)
        rows = fetch_all(
            self.conn,
            """
            SELECT id, habit_id, habit_date, completed_at, note, mood, created_at
            FROM habit_logs
            WHERE habit_id = ?
              AND habit_date >= ?
              AND habit_date <= ?
            ORDER BY habit_date ASC
            """,
            (habit_id, from_date.isoformat(), to_date.isoformat()),
        )
        return rows

    # ---- Stats ----
    def _completion_dates_set(self, habit_id: int, from_date: date, to_date: date) -> set[date]:
        rows = fetch_all(
            self.conn,
            """
            SELECT habit_date
            FROM habit_logs
            WHERE habit_id = ?
              AND habit_date >= ?
              AND habit_date <= ?
            """,
            (habit_id, from_date.isoformat(), to_date.isoformat()),
        )
        return {_parse_date_str(r["habit_date"]) for r in rows}

    def habit_stats(self, habit_id: int, from_date: date, to_date: date) -> Dict[str, Any]:
        _ = self.get_habit(habit_id)

        completion_dates = self._completion_dates_set(habit_id, from_date, to_date)
        completions_count = len(completion_dates)

        # Compute current streak ending at to_date (walk backwards while days exist)
        current_streak = 0
        d = to_date
        while d >= from_date and d in completion_dates:
            current_streak += 1
            d = d - timedelta(days=1)

        # Compute longest streak within [from_date, to_date]
        longest = 0
        run = 0
        d = from_date
        while d <= to_date:
            if d in completion_dates:
                run += 1
                longest = max(longest, run)
            else:
                run = 0
            d = d + timedelta(days=1)

        return {
            "habit_id": habit_id,
            "from_date": from_date,
            "to_date": to_date,
            "completions_count": completions_count,
            "current_streak": current_streak,
            "longest_streak": longest,
        }

    def global_stats(self, from_date: date, to_date: date) -> Dict[str, Any]:
        total_habits_row = fetch_one(self.conn, "SELECT COUNT(*) AS c FROM habits", ())
        active_habits_row = fetch_one(self.conn, "SELECT COUNT(*) AS c FROM habits WHERE is_archived = 0", ())
        total_completions_row = fetch_one(
            self.conn,
            """
            SELECT COUNT(*) AS c FROM habit_logs
            WHERE habit_date >= ? AND habit_date <= ?
            """,
            (from_date.isoformat(), to_date.isoformat()),
        )
        by_date = fetch_all(
            self.conn,
            """
            SELECT habit_date AS date, COUNT(*) AS count
            FROM habit_logs
            WHERE habit_date >= ? AND habit_date <= ?
            GROUP BY habit_date
            ORDER BY habit_date ASC
            """,
            (from_date.isoformat(), to_date.isoformat()),
        )

        return {
            "from_date": from_date,
            "to_date": to_date,
            "total_habits": int((total_habits_row or {"c": 0})["c"]),
            "active_habits": int((active_habits_row or {"c": 0})["c"]),
            "total_completions": int((total_completions_row or {"c": 0})["c"]),
            "completions_by_date": by_date,
        }
