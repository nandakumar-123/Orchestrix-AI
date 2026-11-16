import enum
from datetime import UTC, datetime

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# PostgreSQL convention for constraint naming
POSTGRES_INDEXES_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_`%(constraint_name)s`",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utc_now() -> datetime:
    """Return timezone-aware UTC datetime."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base declarative class with naming conventions."""

    metadata = MetaData(naming_convention=POSTGRES_INDEXES_NAMING_CONVENTION)


class WorkspaceRole(enum.StrEnum):
    """Supported roles for workspace collaborators."""

    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"
    VIEWER = "VIEWER"


class RepositoryMemberRole(enum.StrEnum):
    """Supported roles for repository members in Orchestrix AI."""

    ADMIN = "ADMIN"
    DEVELOPER = "DEVELOPER"
    VIEWER = "VIEWER"


class TaskType(enum.StrEnum):
    """Supported types of engineering tasks."""

    BUG_FIX = "BUG_FIX"
    FEATURE = "FEATURE"
    REFACTOR = "REFACTOR"
    SECURITY = "SECURITY"
    TESTING = "TESTING"
    GENERAL = "GENERAL"


class TaskPriority(enum.StrEnum):
    """Priority levels for engineering tasks."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TaskStatus(enum.StrEnum):
    """Lifecycle statuses for engineering tasks."""

    BACKLOG = "BACKLOG"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PullRequestState(enum.StrEnum):
    """Statuses for tracked pull requests."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    MERGED = "MERGED"


class IndexingJobStatus(enum.StrEnum):
    """Lifecycle statuses for repository intelligence indexing jobs."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TicketPriority(enum.StrEnum):
    """Priority levels for workspace tickets."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TicketStatus(enum.StrEnum):
    """Lifecycle statuses for tickets."""

    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class TicketActivityType(enum.StrEnum):
    """Activity action types for ticket audit and history tracking."""

    CREATED = "CREATED"
    STATUS_CHANGED = "STATUS_CHANGED"
    ASSIGNED = "ASSIGNED"
    PRIORITY_CHANGED = "PRIORITY_CHANGED"
    COMMENTED = "COMMENTED"
    UPDATED = "UPDATED"

