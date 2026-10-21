"""Tailoring no longer spends a credit: a run backed by a credit balance holds nothing.

Past the free allowance, a credit balance still allows a tailoring (entitlement 'credit'),
but the credit is spent at download. So 'credit' runs may have billing_state 'none' and
credits 0. Runs started before this keep their reservation and settle as before.

Revision ID: 0008_free_tailoring
Revises: 0007_analyses
Create Date: 2026-10-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_free_tailoring"
down_revision: str | None = "0007_analyses"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = {
    "credit_state": "(entitlement = 'credit') = (billing_state <> 'none')",
    "credits": "(entitlement = 'credit') = (credits > 0)",
    "reserved_while_pending": "(billing_state = 'reserved') = (entitlement = 'credit' AND status = 'pending')",
}
NEW = {
    # Only a (legacy) credit run ever holds a reservation; it holds credits exactly while it does.
    "credit_state": "billing_state = 'none' OR entitlement = 'credit'",
    "credits": "(credits > 0) = (billing_state <> 'none')",
    "reserved_while_pending": "billing_state <> 'reserved' OR status = 'pending'",
}


def _swap(rules: dict[str, str]) -> None:
    for name, rule in rules.items():
        # 0007 passed full names through the naming convention, which prefixed them again.
        op.execute(f"ALTER TABLE analyses DROP CONSTRAINT IF EXISTS ck_analyses_ck_analyses_{name}")
        op.execute(f"ALTER TABLE analyses DROP CONSTRAINT IF EXISTS ck_analyses_{name}")
        op.execute(f"ALTER TABLE analyses ADD CONSTRAINT ck_analyses_{name} CHECK ({rule})")


def upgrade() -> None:
    _swap(NEW)


def downgrade() -> None:
    # Fails if credit-backed runs without a reservation exist; those can't be expressed before.
    _swap(OLD)
