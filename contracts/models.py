"""Synthetix shared contract v1.0. Identical on both devices. Do not edit."""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

CONTRACT_VERSION = "1.0"
MAX_USERS = 10_000
RATING_ANCHORS = {1: "very low", 2: "low", 3: "mixed", 4: "high", 5: "very high"}
# blocker = prevents a core task; major = materially reduces usefulness or trust;
# minor = inconvenience or preference
Severity = Literal["blocker", "major", "minor"]


class RunMode(str, Enum):
    INTERACTIVE = "interactive"  # agents operate a live web product
    CONCEPT = "concept"          # agents only review supplied material


class JobStatus(str, Enum):      # used for runs and for each synthetic user
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskOutcome(str, Enum):
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    NOT_ATTEMPTED = "not_attempted"


class RatingDimension(str, Enum):
    APPEAL = "appeal"
    USEFULNESS = "usefulness"
    EASE_OF_USE = "ease_of_use"
    TRUST = "trust"
    INTENTION_TO_USE = "intention_to_use"


class TaskSpec(BaseModel):
    task_id: str
    instruction: str
    success_check: str  # "url_contains:<text>" or "text_visible:<text>", checked in code
    max_steps: int = Field(default=15, ge=1, le=50)


class Segment(BaseModel):
    name: str
    weight: float = Field(gt=0)            # relative share of users
    attributes: dict[str, list[str]]       # attribute -> options to sample
    sourced_facts: list[str] = []          # facts with a cited source
    authored_assumptions: list[str] = []   # invented traits, labeled as such
    languages: list[str] = ["en"]


class AudienceSpec(BaseModel):
    spec_version: str
    description: str
    segments: list[Segment] = Field(min_length=1)


class RunConfig(BaseModel):
    product_name: str
    product_version: str
    mode: RunMode
    product_url: Optional[str] = None
    concept_material: Optional[str] = None
    value_proposition: str
    objective: str
    audience: AudienceSpec
    user_count: int = Field(ge=1, le=MAX_USERS, strict=True)
    tasks: list[TaskSpec] = []
    seed: int = 42
    max_concurrency: int = Field(default=5, ge=1, le=50)
    budget_hkd: Optional[float] = Field(default=None, gt=0)
    baseline_run_id: Optional[str] = None

    @model_validator(mode="after")
    def _check_mode_inputs(self):
        if self.mode == RunMode.INTERACTIVE and (not self.product_url or not self.tasks):
            raise ValueError("interactive mode needs product_url and at least one task")
        if self.mode == RunMode.CONCEPT and not self.concept_material:
            raise ValueError("concept mode needs concept_material")
        return self


class SyntheticUser(BaseModel):
    user_id: str
    run_id: str
    segment: str
    profile: dict[str, str]
    sourced_facts: list[str] = []
    authored_assumptions: list[str] = []
    generator_version: str
    status: JobStatus = JobStatus.QUEUED
    attempts: int = 0
    failure_reason: Optional[str] = None


class TraceStep(BaseModel):
    step: int
    url: str
    observation: str                   # short summary of what the agent saw
    action: str                        # click | type | select | scroll | back | done | give_up
    target: Optional[str] = None       # element text or label
    value: Optional[str] = None        # typed text (test data only)
    agent_reason: Optional[str] = None
    screenshot_path: Optional[str] = None


class TaskResult(BaseModel):
    run_id: str
    user_id: str
    task_id: str
    outcome: TaskOutcome
    reason: str
    steps: list[TraceStep] = []


class Rating(BaseModel):
    score: Optional[int] = Field(default=None, ge=1, le=5)
    not_assessable_reason: Optional[str] = None

    @model_validator(mode="after")
    def _exactly_one(self):
        if (self.score is None) == (self.not_assessable_reason is None):
            raise ValueError("set exactly one of score or not_assessable_reason")
        return self


class Problem(BaseModel):
    text: str
    task_id: Optional[str] = None
    severity: Severity


class Evaluation(BaseModel):
    run_id: str
    user_id: str
    mode: RunMode
    ratings: dict[RatingDimension, Rating]
    rating_reasons: str
    strengths: list[str] = []
    problems: list[Problem] = []
    suggestions: list[str] = []
    pricing_feedback: Optional[str] = None

    @model_validator(mode="after")
    def _all_dimensions(self):
        missing = set(RatingDimension) - set(self.ratings)
        if missing:
            raise ValueError(f"missing ratings: {sorted(m.value for m in missing)}")
        return self


class Usage(BaseModel):
    run_id: str
    user_id: str
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    cost_hkd: Optional[float] = None   # None = unknown pricing, never 0


class Finding(BaseModel):
    finding_id: str                    # "<run_id>-f001"
    run_id: str
    theme: str
    severity: Severity
    task_id: Optional[str] = None
    supporting_user_ids: list[str]
    eligible_denominator: int          # completed users who could have hit this issue
    evidence_refs: list[str] = []      # "<user_id>:<task_id>" or "<user_id>:evaluation"
