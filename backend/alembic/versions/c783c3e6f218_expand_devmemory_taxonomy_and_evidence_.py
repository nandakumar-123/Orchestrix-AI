"""expand_devmemory_taxonomy_and_evidence_types

Revision ID: c783c3e6f218
Revises: c7d8e9f0a1b2
Create Date: 2026-11-15 19:27:33.731321

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c783c3e6f218'
down_revision: Union[str, Sequence[str], None] = 'c7d8e9f0a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to expand memory and evidence taxonomy constraints."""
    # 1. Update memory_type check constraint
    op.drop_constraint("ck_devmemory_memory_type", "engineering_memories", type_="check")
    op.create_check_constraint(
        "ck_devmemory_memory_type",
        "engineering_memories",
        "memory_type IN ('ARCHITECTURE_DECISION', 'TECHNICAL_DECISION', 'BUG_FIX', 'VERIFIED_BUGFIX', 'REPO_KNOWLEDGE', 'CODE_EXPLANATION', 'ENGINEERING_CONVENTION', 'REPOSITORY_CONVENTION', 'TASK_OUTCOME', 'IMPLEMENTATION_DISCOVERY', 'ENGINEERING_DISCOVERY', 'KNOWN_LIMITATION', 'VERIFIED_SOLUTION', 'SECURITY_KNOWLEDGE', 'TEST_KNOWLEDGE', 'DEPENDENCY_KNOWLEDGE')",
    )

    # 2. Update evidence_type check constraint
    op.drop_constraint("ck_devmemory_evidence_type", "memory_evidence", type_="check")
    op.create_check_constraint(
        "ck_devmemory_evidence_type",
        "memory_evidence",
        "evidence_type IN ('CODE_REFERENCE', 'GIT_COMMIT', 'CODE_DIFF', 'TEST_RESULT', 'SECURITY_FINDING', 'AGENT_TASK', 'ARCHITECTURE_DOCUMENT', 'USER_DECISION', 'CODE_SNIPPET', 'LOG_TRACE', 'DIFF_PATCH', 'TEST_OUTPUT', 'BENCHMARK_RESULT')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_devmemory_evidence_type", "memory_evidence", type_="check")
    op.create_check_constraint(
        "ck_devmemory_evidence_type",
        "memory_evidence",
        "evidence_type IN ('CODE_SNIPPET', 'LOG_TRACE', 'DIFF_PATCH', 'TEST_OUTPUT', 'SECURITY_FINDING', 'BENCHMARK_RESULT')",
    )

    op.drop_constraint("ck_devmemory_memory_type", "engineering_memories", type_="check")
    op.create_check_constraint(
        "ck_devmemory_memory_type",
        "engineering_memories",
        "memory_type IN ('ARCHITECTURE_DECISION', 'TECHNICAL_DECISION', 'VERIFIED_BUGFIX', 'REPO_KNOWLEDGE', 'CODE_EXPLANATION', 'ENGINEERING_CONVENTION', 'TASK_OUTCOME', 'IMPLEMENTATION_DISCOVERY', 'KNOWN_LIMITATION', 'VERIFIED_SOLUTION')",
    )
