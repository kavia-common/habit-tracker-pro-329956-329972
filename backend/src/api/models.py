"""Pydantic models for the Habit Tracker API (backend container)."""

from __future__ import annotations

from datetime import datetime, date
from typing import List, Optional

from pydantic import BaseModel, Field


class HabitBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Habit name.")
    description: Optional[str] = Field(
        default=None, max_length=2000, description="Optional description."
    )
    color_hex: Optional[str] = Field(
        default=None,
        max_length=16,
        description="Optional color in hex, e.g. '#3B82F6'.",
    )
    icon_name: Optional[str] = Field(
        default=None, max_length=100, description="Optional icon name identifier."
    )
    is_archived: bool = Field(default=False, description="Whether the habit is archived.")


class HabitCreate(HabitBase):
    pass


class HabitUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    color_hex: Optional[str] = Field(default=None, max_length=16)
    icon_name: Optional[str] = Field(default=None, max_length=100)
    is_archived: Optional[bool] = None


class HabitOut(HabitBase):
    id: int = Field(..., description="Habit id.")
    created_at: datetime = Field(..., description="Creation timestamp.")
    updated_at: datetime = Field(..., description="Last update timestamp.")


class CompletionLogCreate(BaseModel):
    habit_date: date = Field(..., description="Local date (YYYY-MM-DD) for the completion.")
    note: Optional[str] = Field(default=None, max_length=2000, description="Optional note.")
    mood: Optional[int] = Field(
        default=None,
        ge=0,
        le=10,
        description="Optional mood/rating integer (0-10).",
    )


class CompletionLogOut(BaseModel):
    id: int
    habit_id: int
    habit_date: date
    completed_at: datetime
    note: Optional[str] = None
    mood: Optional[int] = None
    created_at: datetime


class HabitWithTodayStatus(BaseModel):
    habit: HabitOut
    completed_today: bool = Field(..., description="Whether habit has a completion for the given date.")


class HabitStatsOut(BaseModel):
    habit_id: int = Field(..., description="Habit id.")
    from_date: date = Field(..., description="Start date inclusive.")
    to_date: date = Field(..., description="End date inclusive.")
    completions_count: int = Field(..., description="Number of completion logs in range.")
    current_streak: int = Field(..., description="Current streak up to to_date (consecutive days).")
    longest_streak: int = Field(..., description="Longest streak within range (consecutive days).")


class GlobalStatsOut(BaseModel):
    from_date: date
    to_date: date
    total_habits: int
    active_habits: int
    total_completions: int
    completions_by_date: List[dict] = Field(
        ..., description="List of {date: 'YYYY-MM-DD', count: int} for the range."
    )
