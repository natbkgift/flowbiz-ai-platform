"""Deny-by-default approval policy evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from threading import Lock

from pydantic import BaseModel, Field

from platform_app.approval_models import (
    DECISION_ALLOW,
    DECISION_DENY,
    DECISION_NEEDS_APPROVAL,
    ActionProposal,
)
from platform_app.sqlite_utils import connect_sqlite, prepare_sqlite_database

RISK_ORDER = {
    "LOW": 0,
    "MEDIUM": 1,
    "HIGH": 2,
    "CRITICAL": 3,
}


class ApprovalPolicyRecord(BaseModel):
    policy_id: str
    action_class: str
    target_system: str | None = None
    allowed_mutation_types: tuple[str, ...]
    auto_allow_risk_levels: tuple[str, ...]
    approval_required_from: str | None = None
    is_enabled: bool
    updated_at: str


@dataclass(frozen=True)
class ApprovalPolicyDecision:
    decision: str
    reason_code: str
    reason_detail: str
    approval_required_from: str | None = None


class SQLiteApprovalPolicyStore:
    """SQLite-backed approval policy store.

    Policies enumerate what may be allowed. Missing or non-matching rules deny.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = Lock()
        self._ensure_parent_dir()
        self._init_schema()

    def _ensure_parent_dir(self) -> None:
        parent = Path(self._db_path).expanduser().resolve().parent
        parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self._db_path)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            prepare_sqlite_database(conn)
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS approval_policies (
                  policy_id TEXT PRIMARY KEY,
                  action_class TEXT NOT NULL,
                  target_system TEXT NULL,
                  allowed_mutation_types TEXT NOT NULL,
                  auto_allow_risk_levels TEXT NOT NULL,
                  approval_required_from TEXT NULL,
                  is_enabled INTEGER NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_approval_policies_action_class
                  ON approval_policies(action_class, is_enabled);
                """
            )

    def upsert_policy(
        self,
        *,
        policy_id: str,
        action_class: str,
        allowed_mutation_types: tuple[str, ...],
        auto_allow_risk_levels: tuple[str, ...] = ("LOW", "MEDIUM"),
        target_system: str | None = None,
        approval_required_from: str | None = None,
        is_enabled: bool = True,
    ) -> ApprovalPolicyRecord:
        updated_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        normalized_mutations = _normalize_tuple(allowed_mutation_types)
        normalized_risk_levels = _normalize_tuple(auto_allow_risk_levels)
        if not normalized_mutations:
            raise ValueError("allowed_mutation_types must not be empty")
        if not normalized_risk_levels:
            raise ValueError("auto_allow_risk_levels must not be empty")

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO approval_policies (
                      policy_id,
                      action_class,
                      target_system,
                      allowed_mutation_types,
                      auto_allow_risk_levels,
                      approval_required_from,
                      is_enabled,
                      updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(policy_id) DO UPDATE SET
                      action_class = excluded.action_class,
                      target_system = excluded.target_system,
                      allowed_mutation_types = excluded.allowed_mutation_types,
                      auto_allow_risk_levels = excluded.auto_allow_risk_levels,
                      approval_required_from = excluded.approval_required_from,
                      is_enabled = excluded.is_enabled,
                      updated_at = excluded.updated_at
                    """,
                    (
                        policy_id,
                        action_class,
                        target_system,
                        _serialize_tuple(normalized_mutations),
                        _serialize_tuple(normalized_risk_levels),
                        approval_required_from,
                        int(is_enabled),
                        updated_at,
                    ),
                )

        return ApprovalPolicyRecord(
            policy_id=policy_id,
            action_class=action_class,
            target_system=target_system,
            allowed_mutation_types=normalized_mutations,
            auto_allow_risk_levels=normalized_risk_levels,
            approval_required_from=approval_required_from,
            is_enabled=is_enabled,
            updated_at=updated_at,
        )

    def list_active_policies_for_action(
        self,
        action_class: str,
    ) -> list[ApprovalPolicyRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  policy_id,
                  action_class,
                  target_system,
                  allowed_mutation_types,
                  auto_allow_risk_levels,
                  approval_required_from,
                  is_enabled,
                  updated_at
                FROM approval_policies
                WHERE action_class = ?
                  AND is_enabled = 1
                ORDER BY policy_id ASC
                """,
                (action_class,),
            ).fetchall()
        return [_row_to_policy(row) for row in rows]

    def has_active_policy_for_action(self, action_class: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM approval_policies
                WHERE action_class = ?
                  AND is_enabled = 1
                LIMIT 1
                """,
                (action_class,),
            ).fetchone()
        return row is not None

    def evaluate_policy(
        self,
        *,
        proposal: ActionProposal,
        risk_level: str,
    ) -> ApprovalPolicyDecision:
        policies = self.list_active_policies_for_action(proposal.action_class)
        if not policies:
            return ApprovalPolicyDecision(
                decision=DECISION_DENY,
                reason_code="NO_MATCHING_POLICY",
                reason_detail=(
                    f"No active approval policy matches action class "
                    f"{proposal.action_class}"
                ),
            )

        matching = [
            policy
            for policy in policies
            if _policy_matches_proposal(policy=policy, proposal=proposal)
        ]
        if not matching:
            return ApprovalPolicyDecision(
                decision=DECISION_DENY,
                reason_code="NO_MATCHING_POLICY",
                reason_detail="No active approval policy explicitly allows this proposal",
            )

        for policy in matching:
            if risk_level in policy.auto_allow_risk_levels:
                return ApprovalPolicyDecision(
                    decision=DECISION_ALLOW,
                    reason_code="POLICY_ALLOWED",
                    reason_detail=f"Policy {policy.policy_id} allows this proposal",
                )

        approval_policy = next(
            (policy for policy in matching if policy.approval_required_from),
            None,
        )
        if approval_policy is not None:
            return ApprovalPolicyDecision(
                decision=DECISION_NEEDS_APPROVAL,
                reason_code="APPROVAL_REQUIRED",
                reason_detail=(
                    f"Policy {approval_policy.policy_id} requires approval "
                    f"for {risk_level} risk"
                ),
                approval_required_from=approval_policy.approval_required_from,
            )

        return ApprovalPolicyDecision(
            decision=DECISION_DENY,
            reason_code="RISK_LEVEL_NOT_PERMITTED",
            reason_detail=(
                "Matching policies did not explicitly allow this risk level "
                "or require approval"
            ),
        )


class ApprovalPolicySeed(BaseModel):
    policy_id: str = Field(min_length=1)
    action_class: str = Field(min_length=1)
    target_system: str | None = None
    allowed_mutation_types: tuple[str, ...] = Field(min_length=1)
    auto_allow_risk_levels: tuple[str, ...] = ("LOW", "MEDIUM")
    approval_required_from: str | None = None
    is_enabled: bool = True


def _policy_matches_proposal(
    *,
    policy: ApprovalPolicyRecord,
    proposal: ActionProposal,
) -> bool:
    if policy.target_system is not None and policy.target_system != proposal.target_system:
        return False
    return proposal.mutation_type in policy.allowed_mutation_types


def _normalize_tuple(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = value.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return tuple(normalized)


def _serialize_tuple(values: tuple[str, ...]) -> str:
    return json.dumps(list(values), ensure_ascii=False, separators=(",", ":"))


def _deserialize_tuple(raw: str) -> tuple[str, ...]:
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        return ()
    return tuple(str(item) for item in parsed if str(item).strip())


def _row_to_policy(row: sqlite3.Row) -> ApprovalPolicyRecord:
    return ApprovalPolicyRecord(
        policy_id=str(row["policy_id"]),
        action_class=str(row["action_class"]),
        target_system=str(row["target_system"]) if row["target_system"] else None,
        allowed_mutation_types=_deserialize_tuple(str(row["allowed_mutation_types"])),
        auto_allow_risk_levels=_deserialize_tuple(str(row["auto_allow_risk_levels"])),
        approval_required_from=(
            str(row["approval_required_from"])
            if row["approval_required_from"]
            else None
        ),
        is_enabled=bool(row["is_enabled"]),
        updated_at=str(row["updated_at"]),
    )
