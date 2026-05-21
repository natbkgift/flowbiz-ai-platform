"""Deterministic approval gate risk scoring."""

from __future__ import annotations

from dataclasses import dataclass

from platform_app.approval_models import (
    ACTION_SCOPE_BULK,
    ACTION_SCOPE_GLOBAL,
    MUTATION_DELETE,
    MUTATION_SEND,
    RISK_CRITICAL,
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    ActionProposal,
)

AUTOMATED_REQUESTER_MARKERS = (
    "automation",
    "connector",
    "make",
    "n8n",
    "webhook",
    "zapier",
)


@dataclass(frozen=True)
class RiskScore:
    risk_level: str
    score: int
    reasons: tuple[str, ...]


def score_risk(
    proposal: ActionProposal,
    *,
    recently_denied_payload_hashes: set[str] | None = None,
) -> RiskScore:
    score = 0
    reasons: list[str] = []
    target_scope = proposal.target_scope

    if target_scope.type == ACTION_SCOPE_BULK:
        score += 2
        reasons.append("BULK_SCOPE")
    elif target_scope.type == ACTION_SCOPE_GLOBAL:
        score += 3
        reasons.append("GLOBAL_SCOPE")

    if target_scope.estimated_record_count > 1000:
        score += 4
        reasons.append("RECORD_COUNT_GT_1000")
    elif target_scope.estimated_record_count > 100:
        score += 2
        reasons.append("RECORD_COUNT_GT_100")

    if proposal.mutation_type == MUTATION_DELETE:
        score += 2
        reasons.append("DELETE_MUTATION")
    elif proposal.mutation_type == MUTATION_SEND:
        score += 2
        reasons.append("SEND_MUTATION")

    if proposal.action_class == "config.change":
        score += 2
        reasons.append("CONFIG_CHANGE")

    source = proposal.triggering_signal.source.lower()
    target_system = proposal.target_system.lower()
    if (
        ("test" in source or "staging" in source)
        and "test" not in target_system
        and "staging" not in target_system
        and "sandbox" not in target_system
    ):
        score += 5
        reasons.append("SIGNAL_ORIGIN_MISMATCH")

    if recently_denied_payload_hashes and proposal.payload_hash in recently_denied_payload_hashes:
        score += 2
        reasons.append("RECENTLY_DENIED_PAYLOAD_HASH")

    requester = proposal.requested_by.lower()
    if requester == proposal.connector_id.lower() or any(
        marker in requester for marker in AUTOMATED_REQUESTER_MARKERS
    ):
        score += 1
        reasons.append("AUTOMATED_REQUESTER")

    return RiskScore(
        risk_level=_risk_level_for_score(score),
        score=score,
        reasons=tuple(reasons),
    )


def _risk_level_for_score(score: int) -> str:
    if score >= 9:
        return RISK_CRITICAL
    if score >= 6:
        return RISK_HIGH
    if score >= 3:
        return RISK_MEDIUM
    return RISK_LOW
