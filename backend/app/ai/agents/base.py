"""Agent base class: execution logging, guardrails, LLM access with graceful degradation."""

from __future__ import annotations

import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.providers import LLMError, LLMProvider, get_llm_provider
from app.core.logging import get_logger, log_event, redact_obj
from app.db.base import utcnow
from app.domain.enums import AgentName, ExecutionStatus
from app.models.governance import AIAgentExecution

logger = get_logger(__name__)

I = TypeVar("I", bound=BaseModel)  # noqa: E741
O = TypeVar("O", bound=BaseModel)  # noqa: E741
S = TypeVar("S", bound=BaseModel)


@dataclass
class AgentContext:
    db: Session
    organization_id: uuid.UUID
    triggered_by_id: uuid.UUID | None = None
    workflow_run_id: uuid.UUID | None = None


@dataclass
class RunState:
    flags: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    provider: str = "local"
    model: str = "deterministic-v1"


@dataclass
class AgentOutcome(Generic[O]):
    output: O
    execution: AIAgentExecution
    flags: list[str]


class BaseAgent(ABC, Generic[I, O]):
    name: AgentName
    prompt_key: str | None = None
    prompt_version: str = "deterministic-v1"

    def __init__(self, llm: LLMProvider | None = None) -> None:
        self.llm = llm or get_llm_provider()

    @abstractmethod
    def execute(self, ctx: AgentContext, payload: I, state: RunState) -> O: ...

    def summarize_input(self, payload: I) -> dict[str, Any]:
        """Redacted, size-bounded view of the input for the execution log."""
        data = payload.model_dump(mode="json")
        trimmed = {k: (v[:500] + "…" if isinstance(v, str) and len(v) > 500 else v) for k, v in data.items()}
        return redact_obj(trimmed)

    def run(
        self, ctx: AgentContext, payload: I, *, entity_type: str | None = None, entity_id: uuid.UUID | None = None
    ) -> AgentOutcome[O]:
        execution = AIAgentExecution(
            organization_id=ctx.organization_id,
            agent=self.name,
            status=ExecutionStatus.RUNNING,
            entity_type=entity_type,
            entity_id=entity_id,
            workflow_run_id=ctx.workflow_run_id,
            provider=self.llm.name,
            model=self.llm.model,
            prompt_version=self.prompt_version,
            input_summary=self.summarize_input(payload),
            triggered_by_id=ctx.triggered_by_id,
            started_at=utcnow(),
        )
        ctx.db.add(execution)
        ctx.db.flush()
        state = RunState(
            provider=self.llm.name if self.llm.generative else "local",
            model=self.llm.model if self.llm.generative else "deterministic-v1",
        )
        started = time.perf_counter()
        try:
            output = self.execute(ctx, payload, state)
        except Exception as exc:
            execution.status = ExecutionStatus.FAILED
            execution.error = f"{type(exc).__name__}: {exc}"[:2000]
            execution.finished_at = utcnow()
            execution.latency_ms = int((time.perf_counter() - started) * 1000)
            ctx.db.flush()
            log_event(logger, "agent_failed", logging.ERROR, agent=self.name.value, error=type(exc).__name__)
            raise
        execution.status = ExecutionStatus.BLOCKED if "blocked" in state.flags else ExecutionStatus.SUCCEEDED
        execution.output = output.model_dump(mode="json")
        execution.guardrail_flags = state.flags
        execution.tokens_in, execution.tokens_out = state.tokens_in, state.tokens_out
        execution.provider, execution.model = state.provider, state.model
        execution.finished_at = utcnow()
        execution.latency_ms = int((time.perf_counter() - started) * 1000)
        ctx.db.flush()
        log_event(
            logger,
            "agent_succeeded",
            agent=self.name.value,
            latency_ms=execution.latency_ms,
            flags=state.flags,
            provider=state.provider,
        )
        return AgentOutcome(output=output, execution=execution, flags=state.flags)

    # -- LLM helper -----------------------------------------------------------------
    def ask_llm(self, state: RunState, *, user: str, schema: type[S], system: str | None = None) -> S | None:
        """Call the configured LLM; return None (deterministic fallback) if unavailable or failing."""
        if not self.llm.generative:
            return None
        if system is None:
            from app.ai.prompts import prompt

            assert self.prompt_key, "prompt_key required"
            self.prompt_version, system = prompt(self.prompt_key)
        try:
            result = self.llm.complete_json(system=system, user=user, schema=schema)
        except LLMError as exc:
            state.flags.append(f"llm_unavailable:{type(exc).__name__}")
            log_event(logger, "llm_fallback", logging.WARNING, agent=self.name.value, error=str(exc))
            return None
        state.tokens_in += result.tokens_in
        state.tokens_out += result.tokens_out
        state.provider, state.model = result.provider, result.model
        return result.data
