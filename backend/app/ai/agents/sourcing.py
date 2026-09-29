"""Talent Sourcing Agent: ranks consented talent-pool candidates and recommends approved channels.

It never scrapes external sites: external sourcing is limited to publishing via configured,
approved job-board integrations; internal sourcing is limited to candidates who consented to
talent-pool processing and are not flagged do-not-contact.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.ai.agents.base import AgentContext, BaseAgent, RunState
from app.ai.agents.matching import CandidateSkillIn, MatchInput, RequirementIn, compute_match
from app.domain.enums import AgentName


class PoolCandidate(BaseModel):
    candidate_id: uuid.UUID
    skills: list[CandidateSkillIn]
    years: float | None = None
    embedding: list[float] | None = None
    location: str | None = None


class SourcingInput(BaseModel):
    requirements: list[RequirementIn]
    job_embedding: list[float] | None = None
    pool: list[PoolCandidate]
    approved_channels: list[str] = Field(default_factory=list)
    limit: int = 20

    def summarize(self) -> dict:
        return {"pool_size": len(self.pool), "channels": self.approved_channels}


class SourcedCandidate(BaseModel):
    candidate_id: uuid.UUID
    score: float
    matched: list[str]
    missing: list[str]


class SourcingOutput(BaseModel):
    candidates: list[SourcedCandidate]
    recommended_channels: list[str]


class SourcingAgent(BaseAgent[SourcingInput, SourcingOutput]):
    name = AgentName.SOURCING

    def summarize_input(self, payload: SourcingInput) -> dict:
        return payload.summarize()

    def execute(self, ctx: AgentContext, p: SourcingInput, state: RunState) -> SourcingOutput:
        ranked: list[SourcedCandidate] = []
        for c in p.pool:
            m = compute_match(MatchInput(
                requirements=p.requirements, job_embedding=p.job_embedding, candidate_skills=c.skills,
                candidate_years=c.years, candidate_embedding=c.embedding, candidate_location=c.location,
            ))
            ranked.append(SourcedCandidate(
                candidate_id=c.candidate_id, score=m.score,
                matched=[x.requirement for x in m.matches if x.matched],
                missing=[x.requirement for x in m.matches if not x.matched],
            ))
        ranked.sort(key=lambda r: r.score, reverse=True)
        channels = p.approved_channels or ["careers_site"]
        return SourcingOutput(candidates=ranked[: p.limit], recommended_channels=channels)
