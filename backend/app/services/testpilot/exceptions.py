from __future__ import annotations


class TestPilotError(Exception):
    """Base exception for all TestPilot errors."""

    __test__ = False


class FrameworkNotSupportedError(TestPilotError):
    """Raised when no supported test framework is detected in repository."""

    pass


class TestGenerationError(TestPilotError):
    """Raised when test generation fails or produces invalid tests."""

    pass


class TestApprovalRequiredError(TestPilotError):
    """Raised when an unapproved test suite attempts execution."""

    __test__ = False


class TestExecutionSecurityError(TestPilotError):
    """Raised when command violates security restrictions or path traversal rules."""

    __test__ = False


class TestExecutionTimeoutError(TestPilotError):
    """Raised when test execution exceeds allowed timeout."""

    pass


class CoverageProviderUnavailableError(TestPilotError):
    """Raised when requested test coverage provider is not installed or supported."""

    pass
