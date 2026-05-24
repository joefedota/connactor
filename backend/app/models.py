"""Pydantic models for all API request/response shapes."""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel

Difficulty = Literal["easy", "medium", "hard", "expert"]


class NodeInfo(BaseModel):
    type: str            # "actor" | "movie"
    id: str              # TMDB person_id or movie_id as string
    label: str           # actor name or movie title
    year: Optional[str] = None          # movies only
    popularity: Optional[float] = None  # actors only
    # TMDB image path: `profile_path` for actors, `poster_path` for movies. Frontend
    # prepends `https://image.tmdb.org/t/p/{size}` to construct the final URL.
    image_path: Optional[str] = None
    fame_rank: Optional[int] = None    # actors only — used for path ranking


class GameResponse(BaseModel):
    game_id: str
    source: NodeInfo
    target: NodeInfo
    difficulty: Difficulty


class ValidateRequest(BaseModel):
    source_id: str
    target_id: str
    path: List[str]   # alternating actor/movie IDs as strings


class ValidateResponse(BaseModel):
    valid: bool
    error: Optional[str] = None
    is_complete: bool = False
    is_optimal: Optional[bool] = None  # None until path is complete


class SolveRequest(BaseModel):
    source_id: str
    target_id: str


class SolveResponse(BaseModel):
    hop_count: int
    paths: List[List[NodeInfo]]  # up to 10 optimal paths


class AutocompleteResponse(BaseModel):
    results: List[NodeInfo]


class CompletionInfo(BaseModel):
    hops: int
    time_ms: Optional[int] = None
    completed_at: str


class DailyResponse(BaseModel):
    puzzle_date: str           # YYYY-MM-DD
    puzzle_id: str
    source: NodeInfo
    target: NodeInfo
    optimal_hops: int
    already_completed: bool
    completion: Optional[CompletionInfo] = None
    current_streak: int = 0


class CompleteRequest(BaseModel):
    puzzle_id: Optional[str] = None   # provided for daily games
    source_id: Optional[str] = None   # required when puzzle_id is omitted
    target_id: Optional[str] = None   # required when puzzle_id is omitted
    optimal_hops: Optional[int] = None  # required when puzzle_id is omitted
    hops: int
    time_ms: Optional[int] = None


class CompleteResponse(BaseModel):
    completion_id: str
    puzzle_id: str
    hops: int
    time_ms: Optional[int] = None
    completed_at: str
