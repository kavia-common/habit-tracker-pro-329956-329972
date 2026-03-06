"""FastAPI entrypoint for the Habit Tracker backend.

Provides:
- Habits CRUD
- Completion log endpoints
- Stats endpoints

Database:
- Uses SQLite database file path from environment variable SQLITE_DB.
  This file is produced by the separate `database` container.

Notes for debugging:
- If you get DB errors, verify SQLITE_DB points to an existing file and that the
  schema contains `habits` and `habit_logs` tables (see database/init_db.py).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import List

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware

from src.api.db import get_db
from src.api.models import (
    CompletionLogCreate,
    CompletionLogOut,
    GlobalStatsOut,
    HabitCreate,
    HabitOut,
    HabitStatsOut,
    HabitUpdate,
)
from src.api.services import HabitService

openapi_tags = [
    {"name": "System", "description": "Health and meta endpoints."},
    {"name": "Habits", "description": "CRUD operations for habits."},
    {"name": "Completions", "description": "Log and remove habit completions."},
    {"name": "Stats", "description": "Statistics endpoints (streaks, totals, charts)."},
]

app = FastAPI(
    title="Habit Tracker API",
    description="FastAPI backend for the Habit Tracker app (SQLite-backed).",
    version="0.1.0",
    openapi_tags=openapi_tags,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _service(conn=Depends(get_db)) -> HabitService:
    return HabitService(conn=conn)


# PUBLIC_INTERFACE
@app.get(
    "/",
    tags=["System"],
    summary="Health check",
    description="Basic health check endpoint.",
    operation_id="health_check",
)
def health_check():
    """Health check.

    Returns:
        JSON object with a 'message' key.
    """
    return {"message": "Healthy"}


# PUBLIC_INTERFACE
@app.get(
    "/habits",
    response_model=List[HabitOut],
    tags=["Habits"],
    summary="List habits",
    description="List habits. By default archived habits are excluded.",
    operation_id="list_habits",
)
def list_habits(
    include_archived: bool = Query(False, description="Whether to include archived habits."),
    svc: HabitService = Depends(_service),
):
    """List habits."""
    return svc.list_habits(include_archived=include_archived)


# PUBLIC_INTERFACE
@app.post(
    "/habits",
    response_model=HabitOut,
    status_code=status.HTTP_201_CREATED,
    tags=["Habits"],
    summary="Create habit",
    operation_id="create_habit",
)
def create_habit(payload: HabitCreate, svc: HabitService = Depends(_service)):
    """Create a habit."""
    return svc.create_habit(payload.model_dump())


# PUBLIC_INTERFACE
@app.get(
    "/habits/{habit_id}",
    response_model=HabitOut,
    tags=["Habits"],
    summary="Get habit",
    operation_id="get_habit",
)
def get_habit(habit_id: int, svc: HabitService = Depends(_service)):
    """Get a habit by id."""
    try:
        return svc.get_habit(habit_id)
    except ValueError as e:
        if str(e) == "habit_not_found":
            raise HTTPException(status_code=404, detail="Habit not found") from e
        raise


# PUBLIC_INTERFACE
@app.patch(
    "/habits/{habit_id}",
    response_model=HabitOut,
    tags=["Habits"],
    summary="Update habit",
    operation_id="update_habit",
)
def update_habit(habit_id: int, payload: HabitUpdate, svc: HabitService = Depends(_service)):
    """Update a habit."""
    try:
        return svc.update_habit(habit_id, payload.model_dump(exclude_unset=True))
    except ValueError as e:
        if str(e) == "habit_not_found":
            raise HTTPException(status_code=404, detail="Habit not found") from e
        raise


# PUBLIC_INTERFACE
@app.delete(
    "/habits/{habit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Habits"],
    summary="Delete habit",
    operation_id="delete_habit",
)
def delete_habit(habit_id: int, svc: HabitService = Depends(_service)):
    """Delete a habit and its related logs/reminders (via FK cascade)."""
    try:
        svc.delete_habit(habit_id)
    except ValueError as e:
        if str(e) == "habit_not_found":
            raise HTTPException(status_code=404, detail="Habit not found") from e
        raise
    return None


# PUBLIC_INTERFACE
@app.post(
    "/habits/{habit_id}/completions",
    response_model=CompletionLogOut,
    tags=["Completions"],
    summary="Log completion",
    description="Create or update a completion log for a habit on a given local date.",
    operation_id="log_completion",
)
def log_completion(habit_id: int, payload: CompletionLogCreate, svc: HabitService = Depends(_service)):
    """Log a completion for a habit for a specific date."""
    try:
        row = svc.log_completion(
            habit_id=habit_id,
            habit_date=payload.habit_date,
            note=payload.note,
            mood=payload.mood,
        )
        return row
    except ValueError as e:
        if str(e) == "habit_not_found":
            raise HTTPException(status_code=404, detail="Habit not found") from e
        raise


# PUBLIC_INTERFACE
@app.delete(
    "/habits/{habit_id}/completions",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Completions"],
    summary="Remove completion",
    description="Remove a completion log for a habit on a given local date.",
    operation_id="unlog_completion",
)
def unlog_completion(
    habit_id: int,
    habit_date: date = Query(..., description="Local date (YYYY-MM-DD) to remove completion for."),
    svc: HabitService = Depends(_service),
):
    """Remove a completion for a habit on a specific date."""
    try:
        svc.unlog_completion(habit_id=habit_id, habit_date=habit_date)
    except ValueError as e:
        if str(e) == "habit_not_found":
            raise HTTPException(status_code=404, detail="Habit not found") from e
        raise
    return None


# PUBLIC_INTERFACE
@app.get(
    "/habits/{habit_id}/completions",
    response_model=List[CompletionLogOut],
    tags=["Completions"],
    summary="List completions",
    description="List completion logs for a habit between from_date and to_date (inclusive).",
    operation_id="list_completions",
)
def list_completions(
    habit_id: int,
    from_date: date = Query(..., description="Start date inclusive (YYYY-MM-DD)."),
    to_date: date = Query(..., description="End date inclusive (YYYY-MM-DD)."),
    svc: HabitService = Depends(_service),
):
    """List completion logs for a habit in a date range."""
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be <= to_date")
    try:
        return svc.list_completions(habit_id=habit_id, from_date=from_date, to_date=to_date)
    except ValueError as e:
        if str(e) == "habit_not_found":
            raise HTTPException(status_code=404, detail="Habit not found") from e
        raise


# PUBLIC_INTERFACE
@app.get(
    "/habits/{habit_id}/stats",
    response_model=HabitStatsOut,
    tags=["Stats"],
    summary="Habit stats",
    description="Get stats (count, current streak, longest streak) for a habit over a date range.",
    operation_id="habit_stats",
)
def habit_stats(
    habit_id: int,
    from_date: date = Query(..., description="Start date inclusive (YYYY-MM-DD)."),
    to_date: date = Query(..., description="End date inclusive (YYYY-MM-DD)."),
    svc: HabitService = Depends(_service),
):
    """Compute habit stats for a date range."""
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be <= to_date")
    try:
        return svc.habit_stats(habit_id=habit_id, from_date=from_date, to_date=to_date)
    except ValueError as e:
        if str(e) == "habit_not_found":
            raise HTTPException(status_code=404, detail="Habit not found") from e
        raise


# PUBLIC_INTERFACE
@app.get(
    "/stats/global",
    response_model=GlobalStatsOut,
    tags=["Stats"],
    summary="Global stats",
    description="Get global stats over a date range (habit counts, total completions, completions by date).",
    operation_id="global_stats",
)
def global_stats(
    days: int = Query(30, ge=1, le=3650, description="Number of days back from today (inclusive)."),
    svc: HabitService = Depends(_service),
):
    """Compute global stats for the last N days (inclusive)."""
    to_date = date.today()
    from_date = to_date - timedelta(days=days - 1)
    return svc.global_stats(from_date=from_date, to_date=to_date)
