"""Read-only SQL aggregate owner for application observability."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cognis.store.models import (
    Agent,
    ChannelAccountRow,
    ChannelDeliveryOutboxRow,
    Conversation,
    DirectTurnRequestRow,
    ExecutorRow,
    Session,
    StepRun,
    Task,
    User,
)

_SAFE_LABEL = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,95}$")
_SAFE_EMAIL = re.compile(r"^[^@\s]{1,128}@[^\s@]{1,255}$")
_UUID_LABEL = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

ACTIVE_TURN_STATUSES = frozenset({"claimed", "running", "absorbing"})
ACTIVE_STEP_STATUSES = frozenset({"running", "evaluating"})
_ORIGIN_VALUES = frozenset({"web", "channel", "api", "task", "schedule", "system", "other"})
_CHANNEL_CONTEXT_TYPES = frozenset(
    {"signal", "telegram", "whatsapp", "slack", "discord", "matrix", "sms", "email", "channel"}
)


def normalize_slug(value: Any, *, fallback: str = "unknown") -> str:
    candidate = str(value).strip().lower() if value is not None else ""
    return (
        candidate
        if _SAFE_LABEL.fullmatch(candidate) and not _UUID_LABEL.fullmatch(candidate)
        else fallback
    )


def normalize_email(value: Any) -> str:
    candidate = str(value).strip().lower() if value is not None else ""
    return candidate if _SAFE_EMAIL.fullmatch(candidate) else "unknown"


def normalize_executor_owner(value: Any) -> str:
    return "shared" if value == "shared" else normalize_email(value)


def normalize_status(value: Any) -> str:
    candidate = normalize_slug(value)
    return candidate if candidate != "unknown" else "unknown"


def normalize_provider(value: Any) -> str:
    return normalize_slug(value, fallback="unknown")


def normalize_model(value: Any) -> str:
    return normalize_slug(value, fallback="unknown")


def normalize_profile(value: Any) -> str:
    if value is None:
        return "none"
    return normalize_slug(value, fallback="unknown")


def normalize_origin(value: Any) -> str:
    candidate = normalize_slug(value, fallback="")
    if candidate in _CHANNEL_CONTEXT_TYPES:
        return "channel"
    return candidate if candidate in _ORIGIN_VALUES else "other"


def normalize_inherited(value: Any, *, missing: str = "inherit") -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return missing
    return normalize_slug(value, fallback="unknown")


@dataclass(frozen=True, slots=True)
class ObservabilitySnapshot:
    collected_at: datetime
    metric_rows: tuple[
        tuple[str, str, tuple[str, ...], tuple[tuple[Mapping[str, str], float], ...]], ...
    ]
    cardinality_omitted: tuple[tuple[str, int], ...] = ()
    executor_slugs: Mapping[str, tuple[str, str]] = MappingProxyType({})


async def _bounded_rows(
    session: AsyncSession, statement: Any, limit: int
) -> tuple[list[Any], bool]:
    """Read at most cap+1 grouped rows and reject the whole family on overflow."""

    rows = list((await session.execute(statement.limit(limit + 1))).all())
    return ([], True) if len(rows) > limit else (rows, False)


def _metric_rows(
    rows: list[Any],
    labels: tuple[str, ...],
    *,
    normalizers: Mapping[str, Any] | None = None,
) -> tuple[tuple[dict[str, str], float], ...]:
    normalizers = normalizers or {}
    merged: dict[tuple[str, ...], tuple[dict[str, str], float]] = {}
    for row in rows:
        label_values = {
            label: normalizers.get(label, normalize_slug)(row[index])
            for index, label in enumerate(labels)
        }
        key = tuple(label_values[label] for label in labels)
        value = float(max(0, int(row[-1] or 0)))
        existing = merged.get(key)
        if existing is None:
            merged[key] = (label_values, value)
        else:
            merged[key] = (existing[0], existing[1] + value)
    return tuple(
        sorted(
            merged.values(),
            key=lambda item: tuple(item[0][label] for label in labels),
        )
    )


def _family(
    name: str,
    documentation: str,
    labels: tuple[str, ...],
    rows: tuple[tuple[dict[str, str], float], ...],
) -> tuple[str, str, tuple[str, ...], tuple[tuple[dict[str, str], float], ...]]:
    return name, documentation, labels, rows


async def collect_observability_snapshot(
    session: AsyncSession,
    *,
    max_family_cardinality: int = 1000,
) -> ObservabilitySnapshot:
    """Collect bounded, read-only inventory aggregates."""

    limit = max(1, max_family_cardinality)
    families: list[tuple[str, str, tuple[str, ...], tuple[tuple[dict[str, str], float], ...]]] = []
    omitted: list[tuple[str, int]] = []

    async def grouped(
        name: str,
        documentation: str,
        labels: tuple[str, ...],
        statement: Any,
        *,
        normalizers: Mapping[str, Any] | None = None,
    ) -> None:
        rows, overflow = await _bounded_rows(session, statement, limit)
        metric_rows = () if overflow else _metric_rows(rows, labels, normalizers=normalizers)
        if len(metric_rows) > limit:
            overflow = True
            metric_rows = ()
        families.append(_family(name, documentation, labels, metric_rows))
        if overflow:
            omitted.append((name.removeprefix("cognis_"), 1))

    await grouped(
        "cognis_users",
        "Configured user accounts by status.",
        ("status",),
        select(User.is_active, func.count(User.email)).group_by(User.is_active),
        normalizers={"status": lambda value: "active" if value else "disabled"},
    )
    await grouped(
        "cognis_agents",
        "Configured agents by owner, canonical agent, type, and status.",
        ("user", "agent", "type", "status"),
        select(
            Agent.owner_email,
            Agent.agent_id,
            Agent.agent_type,
            Agent.status,
            func.count(Agent.agent_id),
        ).group_by(Agent.owner_email, Agent.agent_id, Agent.agent_type, Agent.status),
        normalizers={
            "user": normalize_email,
            "agent": normalize_slug,
            "type": normalize_slug,
            "status": normalize_status,
        },
    )
    await grouped(
        "cognis_conversations",
        "Conversations by owner, agent, profile, origin, and lifecycle status.",
        ("user", "agent", "profile", "origin", "status"),
        select(
            Conversation.user_email,
            Agent.agent_id,
            Conversation.agent_profile_id,
            Conversation.context_type,
            Conversation.status,
            func.count(Conversation.conversation_id),
        )
        .join(Agent, Agent.agent_id == Conversation.agent_id)
        .group_by(
            Conversation.user_email,
            Agent.agent_id,
            Conversation.agent_profile_id,
            Conversation.context_type,
            Conversation.status,
        ),
        normalizers={
            "user": normalize_email,
            "agent": normalize_slug,
            "profile": normalize_profile,
            "origin": normalize_origin,
            "status": normalize_status,
        },
    )
    await grouped(
        "cognis_sessions",
        "Sessions by lifecycle and effective model dimensions.",
        ("user", "agent", "provider", "model", "profile", "origin", "status"),
        select(
            Session.user_email,
            Agent.agent_id,
            Session.model_override_provider_id,
            Session.model_override,
            Session.agent_profile_id,
            Conversation.context_type,
            Session.status,
            func.count(Session.session_id),
        )
        .join(Agent, Agent.agent_id == Session.agent_id)
        .join(Conversation, Conversation.conversation_id == Session.conversation_id)
        .group_by(
            Session.user_email,
            Agent.agent_id,
            Session.model_override_provider_id,
            Session.model_override,
            Session.agent_profile_id,
            Conversation.context_type,
            Session.status,
        ),
        normalizers={
            "user": normalize_email,
            "agent": normalize_slug,
            "provider": normalize_inherited,
            "model": normalize_inherited,
            "profile": normalize_profile,
            "origin": normalize_origin,
            "status": normalize_status,
        },
    )
    await grouped(
        "cognis_turn_requests",
        "Durable direct-turn requests by domain status.",
        ("user", "agent", "provider", "model", "profile", "origin", "status"),
        select(
            DirectTurnRequestRow.user_id,
            DirectTurnRequestRow.agent_id,
            Session.model_override_provider_id,
            Session.model_override,
            Session.agent_profile_id,
            Conversation.context_type,
            DirectTurnRequestRow.status,
            func.count(DirectTurnRequestRow.request_id),
        )
        .outerjoin(Session, Session.session_id == DirectTurnRequestRow.session_id)
        .outerjoin(
            Conversation, Conversation.conversation_id == DirectTurnRequestRow.conversation_id
        )
        .group_by(
            DirectTurnRequestRow.user_id,
            DirectTurnRequestRow.agent_id,
            Session.model_override_provider_id,
            Session.model_override,
            Session.agent_profile_id,
            Conversation.context_type,
            DirectTurnRequestRow.status,
        ),
        normalizers={
            "user": normalize_email,
            "agent": normalize_slug,
            "provider": normalize_inherited,
            "model": normalize_inherited,
            "profile": normalize_profile,
            "origin": normalize_origin,
            "status": normalize_turn_status,
        },
    )
    await grouped(
        "cognis_turns_active",
        "Active durable turns by domain status.",
        ("user", "agent", "provider", "model", "profile", "origin", "status"),
        select(
            DirectTurnRequestRow.user_id,
            DirectTurnRequestRow.agent_id,
            Session.model_override_provider_id,
            Session.model_override,
            Session.agent_profile_id,
            Conversation.context_type,
            DirectTurnRequestRow.status,
            func.count(DirectTurnRequestRow.request_id),
        )
        .outerjoin(Session, Session.session_id == DirectTurnRequestRow.session_id)
        .outerjoin(
            Conversation, Conversation.conversation_id == DirectTurnRequestRow.conversation_id
        )
        .where(DirectTurnRequestRow.status.in_(ACTIVE_TURN_STATUSES))
        .group_by(
            DirectTurnRequestRow.user_id,
            DirectTurnRequestRow.agent_id,
            Session.model_override_provider_id,
            Session.model_override,
            Session.agent_profile_id,
            Conversation.context_type,
            DirectTurnRequestRow.status,
        ),
        normalizers={
            "user": normalize_email,
            "agent": normalize_slug,
            "provider": normalize_inherited,
            "model": normalize_inherited,
            "profile": normalize_profile,
            "origin": normalize_origin,
            "status": normalize_turn_status,
        },
    )
    await grouped(
        "cognis_tasks",
        "Durable tasks by domain status.",
        ("user", "agent", "profile", "origin", "status"),
        select(
            Task.created_by,
            Task.agent_id,
            Task.agent_profile_id,
            Task.source_type,
            Task.status,
            func.count(Task.task_id),
        ).group_by(
            Task.created_by, Task.agent_id, Task.agent_profile_id, Task.source_type, Task.status
        ),
        normalizers={
            "user": normalize_email,
            "agent": normalize_slug,
            "profile": normalize_profile,
            "origin": normalize_origin,
            "status": normalize_status,
        },
    )
    await grouped(
        "cognis_executions_active",
        "Running or evaluating workflow executions by canonical dimensions.",
        ("user", "agent", "provider", "model", "profile", "origin", "type", "status"),
        select(
            Task.created_by,
            Task.agent_id,
            Session.model_override_provider_id,
            Session.model_override,
            StepRun.agent_profile_id,
            Conversation.context_type,
            StepRun.step_type,
            StepRun.status,
            func.count(StepRun.step_run_id),
        )
        .join(Task, Task.task_id == StepRun.task_id)
        .outerjoin(Session, Session.session_id == StepRun.session_id)
        .outerjoin(Conversation, Conversation.conversation_id == StepRun.conversation_id)
        .where(StepRun.status.in_(ACTIVE_STEP_STATUSES))
        .group_by(
            Task.created_by,
            Task.agent_id,
            Session.model_override_provider_id,
            Session.model_override,
            StepRun.agent_profile_id,
            Conversation.context_type,
            StepRun.step_type,
            StepRun.status,
        ),
        normalizers={
            "user": normalize_email,
            "agent": normalize_slug,
            "provider": normalize_inherited,
            "model": normalize_inherited,
            "profile": normalize_profile,
            "origin": normalize_origin,
            "type": normalize_slug,
            "status": normalize_status,
        },
    )
    await grouped(
        "cognis_channel_accounts",
        "Configured channel accounts by type and state.",
        ("user", "agent", "profile", "channel", "status"),
        select(
            ChannelAccountRow.user_email,
            ChannelAccountRow.agent_id,
            ChannelAccountRow.default_agent_profile_id,
            ChannelAccountRow.channel_type,
            case((ChannelAccountRow.enabled.is_(True), "enabled"), else_="disabled"),
            func.count(ChannelAccountRow.account_id),
        ).group_by(
            ChannelAccountRow.user_email,
            ChannelAccountRow.agent_id,
            ChannelAccountRow.default_agent_profile_id,
            ChannelAccountRow.channel_type,
            case((ChannelAccountRow.enabled.is_(True), "enabled"), else_="disabled"),
        ),
        normalizers={
            "user": normalize_email,
            "agent": normalize_slug,
            "profile": normalize_profile,
            "channel": normalize_slug,
            "status": normalize_status,
        },
    )
    await grouped(
        "cognis_channel_deliveries",
        "Channel delivery rows by type and state.",
        ("user", "agent", "channel", "status"),
        select(
            ChannelDeliveryOutboxRow.user_email,
            Conversation.agent_id,
            ChannelDeliveryOutboxRow.channel_type,
            ChannelDeliveryOutboxRow.status,
            func.count(ChannelDeliveryOutboxRow.delivery_id),
        )
        .join(
            Conversation, Conversation.conversation_id == ChannelDeliveryOutboxRow.conversation_id
        )
        .group_by(
            ChannelDeliveryOutboxRow.user_email,
            Conversation.agent_id,
            ChannelDeliveryOutboxRow.channel_type,
            ChannelDeliveryOutboxRow.status,
        ),
        normalizers={
            "user": normalize_email,
            "agent": normalize_slug,
            "channel": normalize_slug,
            "status": normalize_status,
        },
    )
    await grouped(
        "cognis_executors",
        "Configured executors by owner, type, and configuration status.",
        ("user", "type", "status"),
        select(
            func.coalesce(ExecutorRow.owner_email, "shared"),
            ExecutorRow.executor_type,
            ExecutorRow.status,
            func.count(ExecutorRow.executor_id),
        ).group_by(ExecutorRow.owner_email, ExecutorRow.executor_type, ExecutorRow.status),
        normalizers={
            "user": normalize_executor_owner,
            "type": normalize_slug,
            "status": normalize_status,
        },
    )
    await grouped(
        "cognis_executor_state",
        "Configured executor runtime state by safe unique name.",
        ("user", "executor", "type", "status"),
        select(
            func.coalesce(ExecutorRow.owner_email, "shared"),
            ExecutorRow.name,
            ExecutorRow.executor_type,
            ExecutorRow.runtime_state,
            func.count(ExecutorRow.executor_id),
        ).group_by(
            ExecutorRow.owner_email,
            ExecutorRow.name,
            ExecutorRow.executor_type,
            ExecutorRow.runtime_state,
        ),
        normalizers={
            "user": normalize_executor_owner,
            "executor": normalize_slug,
            "type": normalize_slug,
            "status": normalize_status,
        },
    )

    executor_rows, executor_overflow = await _bounded_rows(
        session,
        select(ExecutorRow.executor_id, ExecutorRow.name, ExecutorRow.owner_email),
        limit,
    )
    executor_slugs: dict[str, tuple[str, str]] = {}
    if executor_overflow:
        # This is an internal lookup for LSP attribution, not another exported
        # metric family.  The public executor family records its own omission.
        executor_slugs = {}
    else:
        candidates: dict[tuple[str, str], list[str]] = {}
        for executor_id, name, owner_email in executor_rows:
            slug = normalize_slug(name, fallback="")
            if slug:
                owner = normalize_executor_owner(owner_email)
                candidates.setdefault((owner, slug), []).append(str(executor_id))
        for (owner, slug), executor_ids in candidates.items():
            if len(executor_ids) == 1:
                executor_id = executor_ids[0]
                executor_slugs[executor_id] = (slug, owner)

    now = datetime.now(UTC)
    windows = (
        ("5m", timedelta(minutes=5)),
        ("1h", timedelta(hours=1)),
        ("24h", timedelta(hours=24)),
        ("7d", timedelta(days=7)),
    )
    user_active_rows: list[Any] = []
    agent_active_rows: list[Any] = []
    user_active_overflow = False
    agent_active_overflow = False
    for window, duration in windows:
        rows, overflow = await _bounded_rows(
            session,
            select(DirectTurnRequestRow.user_id, func.count(DirectTurnRequestRow.request_id))
            .where(DirectTurnRequestRow.created_at >= now - duration)
            .group_by(DirectTurnRequestRow.user_id),
            limit,
        )
        if overflow:
            user_active_overflow = True
        user_active_rows.extend((window, row[0], 1) for row in rows)
        rows, overflow = await _bounded_rows(
            session,
            select(
                DirectTurnRequestRow.user_id,
                DirectTurnRequestRow.agent_id,
                Agent.agent_type,
                func.count(DirectTurnRequestRow.request_id),
            )
            .join(Agent, Agent.agent_id == DirectTurnRequestRow.agent_id)
            .where(DirectTurnRequestRow.created_at >= now - duration)
            .group_by(
                DirectTurnRequestRow.user_id, DirectTurnRequestRow.agent_id, Agent.agent_type
            ),
            limit,
        )
        if overflow:
            agent_active_overflow = True
        agent_active_rows.extend((window, row[0], row[1], row[2], 1) for row in rows)
    user_active = (
        ()
        if user_active_overflow
        else _metric_rows(
            user_active_rows,
            ("window", "user"),
            normalizers={"user": normalize_email},
        )
    )
    agent_active = (
        ()
        if agent_active_overflow
        else _metric_rows(
            agent_active_rows,
            ("window", "user", "agent", "type"),
            normalizers={
                "user": normalize_email,
                "agent": normalize_slug,
                "type": normalize_slug,
            },
        )
    )
    if len(user_active) > limit:
        user_active_overflow = True
        user_active = ()
    if len(agent_active) > limit:
        agent_active_overflow = True
        agent_active = ()
    families.append(
        _family(
            "cognis_users_active",
            "Users with admitted work in fixed rolling windows.",
            ("window", "user"),
            user_active,
        )
    )
    families.append(
        _family(
            "cognis_agents_active",
            "Agents with admitted work in fixed rolling windows.",
            ("window", "user", "agent", "type"),
            agent_active,
        )
    )
    if user_active_overflow:
        omitted.append(("users_active", 1))
    if agent_active_overflow:
        omitted.append(("agents_active", 1))

    return ObservabilitySnapshot(
        collected_at=now,
        metric_rows=tuple(
            (
                name,
                documentation,
                labels,
                tuple((MappingProxyType(label_values), value) for label_values, value in rows),
            )
            for name, documentation, labels, rows in families
        ),
        cardinality_omitted=tuple(omitted),
        executor_slugs=MappingProxyType(executor_slugs),
    )


def normalize_turn_status(value: Any) -> str:
    candidate = str(value).strip().lower() if value is not None else ""
    return (
        candidate
        if candidate
        in {
            "queued",
            "claimed",
            "running",
            "recoverable",
            "completed",
            "failed",
            "cancelled",
            "absorbed",
            "ambiguous",
            "absorbing",
        }
        else "ambiguous"
    )


__all__ = [
    "ACTIVE_TURN_STATUSES",
    "ACTIVE_STEP_STATUSES",
    "ObservabilitySnapshot",
    "collect_observability_snapshot",
    "normalize_email",
    "normalize_executor_owner",
    "normalize_inherited",
    "normalize_model",
    "normalize_origin",
    "normalize_profile",
    "normalize_provider",
    "normalize_slug",
    "normalize_status",
]
