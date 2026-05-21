"""Approval gate request, decision, and audit models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ACTION_SCOPE_SINGLE = "single"
ACTION_SCOPE_BULK = "bulk"
ACTION_SCOPE_GLOBAL = "global"

MUTATION_CREATE = "create"
MUTATION_UPDATE = "update"
MUTATION_DELETE = "delete"
MUTATION_STATUS_CHANGE = "status_change"
MUTATION_SEND = "send"
MUTATION_OTHER = "other"

DECISION_ALLOW = "ALLOW"
DECISION_DENY = "DENY"
DECISION_NEEDS_APPROVAL = "NEEDS_APPROVAL"

RISK_LOW = "LOW"
RISK_MEDIUM = "MEDIUM"
RISK_HIGH = "HIGH"
RISK_CRITICAL = "CRITICAL"

AUDIT_EVENT_DECISION_MADE = "DECISION_MADE"


class TargetScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["single", "bulk", "global"]
    estimated_record_count: int = Field(ge=0)


class TriggeringSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1)
    signal_id: str = Field(min_length=1)
    signal_timestamp: datetime


class ActionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    action_class: str = Field(min_length=1)
    target_system: str = Field(min_length=1)
    target_scope: TargetScope
    mutation_type: Literal[
        "create",
        "update",
        "delete",
        "status_change",
        "send",
        "other",
    ]
    payload_summary: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)
    triggering_signal: TriggeringSignal
    submitted_at: datetime
    requested_by: str = Field(min_length=1)

    @field_validator("payload_hash")
    @classmethod
    def _validate_payload_hash(cls, value: str) -> str:
        normalized = value.lower()
        if any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError("payload_hash must be a lowercase or uppercase SHA-256 hex digest")
        return normalized


class DecisionResponse(BaseModel):
    proposal_id: str
    decision: Literal["ALLOW", "DENY", "NEEDS_APPROVAL"]
    decision_id: str
    decision_timestamp: str
    reason_code: str
    reason_detail: str
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    approval_required_from: str | None = None
    approval_queue_id: str | None = None
    rollback_checklist_id: str | None = None


class AuditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audit_id: str
    event_type: str = AUDIT_EVENT_DECISION_MADE
    proposal_id: str
    decision_id: str | None = None
    timestamp: str
    actor: str
    action_class: str
    target_system: str
    target_scope: dict[str, Any]
    risk_level: str
    decision: str | None = None
    reason_code: str | None = None
    payload_hash: str
    full_proposal_snapshot: dict[str, Any]


class ConnectorRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connector_id: str = Field(min_length=1)
    connector_name: str = Field(min_length=1)
    allowed_action_classes: tuple[str, ...] = Field(min_length=1)
    api_key: str = Field(min_length=1)
    callback_url: str | None = None
    disabled: bool = False

    @field_validator("allowed_action_classes")
    @classmethod
    def _normalize_action_classes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            action_class = item.strip()
            if not action_class or action_class in seen:
                continue
            seen.add(action_class)
            normalized.append(action_class)
        if not normalized:
            raise ValueError("allowed_action_classes must include at least one action class")
        return tuple(normalized)


class ConnectorRegistrationRecord(BaseModel):
    connector_id: str
    connector_name: str
    allowed_action_classes: tuple[str, ...]
    callback_url: str | None = None
    disabled: bool = False
    created_at: str
    updated_at: str
