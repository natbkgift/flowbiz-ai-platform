"""Seed the Safe Automation Approval Gate with one dogfood connector + policies.

Run from the repo root:

    python scripts/seed_approval_gate_dogfood.py

Idempotent (upsert). Prints the connector API key to use in curl / n8n / Make.

This is single-operator dogfood tooling. The default API key is a placeholder —
override it with the DOGFOOD_GATE_API_KEY env var, and rotate before any shared use.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
root_str = str(ROOT)
if root_str not in sys.path:
    sys.path.insert(0, root_str)

from platform_app.approval_models import ConnectorRegistration  # noqa: E402
from platform_app.approval_policy import SQLiteApprovalPolicyStore  # noqa: E402
from platform_app.approval_records import resolve_approval_gate_db_path  # noqa: E402
from platform_app.config import get_settings  # noqa: E402
from platform_app.connector_store import SQLiteConnectorStore  # noqa: E402

CONNECTOR_ID = "dogfood-n8n"
API_KEY = os.environ.get("DOGFOOD_GATE_API_KEY", "dogfood-gate-key-rotate-me-7f3a9c21b8")


def main() -> None:
    settings = get_settings()
    db_path = resolve_approval_gate_db_path(settings.approval_gate_sqlite_path)

    connectors = SQLiteConnectorStore(db_path)
    policies = SQLiteApprovalPolicyStore(db_path)

    connectors.upsert_connector(
        ConnectorRegistration(
            connector_id=CONNECTOR_ID,
            connector_name="Dogfood n8n/Make connector",
            allowed_action_classes=(
                "crm.contact.update",
                "crm.campaign.send",
                "crm.deal.status_change",
            ),
            api_key=API_KEY,
        )
    )

    # Policy A — low/medium-risk contact updates auto-allow.
    policies.upsert_policy(
        policy_id="pol-contact-update",
        action_class="crm.contact.update",
        allowed_mutation_types=("update",),
        auto_allow_risk_levels=("LOW", "MEDIUM"),
    )

    # Policy B — campaign sends auto-allow only at LOW; HIGH/CRITICAL require approval.
    policies.upsert_policy(
        policy_id="pol-campaign-send",
        action_class="crm.campaign.send",
        allowed_mutation_types=("send",),
        auto_allow_risk_levels=("LOW",),
        approval_required_from="founder",
    )

    # NOTE: crm.deal.status_change is intentionally left WITHOUT a policy so a
    #       proposal for it demonstrates deny-by-default (NO_MATCHING_POLICY).

    print("Approval gate dogfood seed complete.")
    print(f"  DB:           {db_path}")
    print(f"  connector_id: {CONNECTOR_ID}")
    print(f"  api_key:      {API_KEY}")
    print("  policy pol-contact-update : crm.contact.update -> auto-allow LOW/MEDIUM")
    print("  policy pol-campaign-send  : crm.campaign.send  -> approval at HIGH/CRITICAL")
    print("  (crm.deal.status_change has NO policy -> deny-by-default demo)")


if __name__ == "__main__":
    main()
