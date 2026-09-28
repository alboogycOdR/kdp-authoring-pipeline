from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StructuredEditorialFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    severity: Literal["note", "minor", "major", "critical"]
    location: str = Field(min_length=1, max_length=300)
    issue: str = Field(min_length=1, max_length=3000)
    evidence: str = Field(min_length=1, max_length=3000)
    recommended_action: str = Field(min_length=1, max_length=2000)


class StructuredEditorialOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["pass", "review", "fail"]
    supplied_context_confirmed: bool
    summary: str = Field(min_length=1, max_length=4000)
    findings: list[StructuredEditorialFinding] = Field(max_length=50)
    required_followups: list[str] = Field(max_length=30)
