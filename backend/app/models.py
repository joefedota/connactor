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
