"""Create event inbox, application projection and atomic completion audit."""

import sqlalchemy as sa
from alembic import op

revision = "001"
down_revision = None


def upgrade():
    op.create_table(
        "gateway_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("application_id", sa.String(64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(32)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "event_id", name="uq_event_identity"),
        sa.CheckConstraint("sequence > 0", name="ck_event_sequence"),
        sa.CheckConstraint("attempts >= 0", name="ck_event_attempts"),
        sa.CheckConstraint("status IN ('queued','processed','rejected')", name="ck_event_status"),
    )
    op.create_index("ix_gateway_events_tenant_id", "gateway_events", ["tenant_id"])
    op.create_index("ix_events_work", "gateway_events", ["status", "available_at", "created_at"])
    op.create_table(
        "gateway_applications",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("application_id", sa.String(64), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.CheckConstraint("last_sequence >= 0", name="ck_application_sequence"),
        sa.CheckConstraint(
            "status IN ('pending','submitted','approved','declined','funded')",
            name="ck_application_status",
        ),
    )
    op.create_table(
        "gateway_audit",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False, unique=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(32)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("gateway_audit")
    op.drop_table("gateway_applications")
    op.drop_table("gateway_events")
