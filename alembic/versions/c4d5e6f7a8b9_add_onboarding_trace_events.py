"""persist privacy-safe onboarding model call telemetry

Revision ID: c4d5e6f7a8b9
Revises: b4c5d6e7f8a9
"""

from collections.abc import Sequence

from alembic import op


revision: str = "c4d5e6f7a8b9"
down_revision: str | None = "b4c5d6e7f8a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS onboarding_trace_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id UUID REFERENCES onboarding_sessions(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            turn_id UUID NOT NULL,
            parent_call_id UUID,
            event_type VARCHAR(32) NOT NULL,
            operation VARCHAR(64) NOT NULL,
            attempt_number INTEGER NOT NULL DEFAULT 1,
            provider VARCHAR(64),
            model VARCHAR(128),
            status VARCHAR(32) NOT NULL,
            latency_ms INTEGER,
            context_tokens INTEGER NOT NULL DEFAULT 0,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            usage_source VARCHAR(16) NOT NULL DEFAULT 'estimated',
            retry_count INTEGER NOT NULL DEFAULT 0,
            fallback_used BOOLEAN NOT NULL DEFAULT FALSE,
            error_category VARCHAR(64),
            error_status INTEGER,
            metadata JSONB NOT NULL DEFAULT '{}'::json,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_onboarding_trace_session_id ON onboarding_trace_events (session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_onboarding_trace_user_id ON onboarding_trace_events (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_onboarding_trace_turn_id ON onboarding_trace_events (turn_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_onboarding_trace_parent_call_id ON onboarding_trace_events (parent_call_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_onboarding_trace_operation ON onboarding_trace_events (operation)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_onboarding_trace_status ON onboarding_trace_events (status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_onboarding_trace_error_category ON onboarding_trace_events (error_category)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS onboarding_trace_events")
