from __future__ import annotations


class SecureFlowError(Exception):
    """Base exception for all SecureFlow errors."""

    pass


class ScannerUnavailableError(SecureFlowError):
    """Raised when a requested scanner tool is not installed or available."""

    pass


class ScannerTimeoutError(SecureFlowError):
    """Raised when security scanner execution exceeds the allowed timeout limit."""

    pass


class SecretLeakagePreventedError(SecureFlowError):
    """Raised when an unredacted credential was prevented from leaking to logs or findings."""

    pass


class FindingFingerprintError(SecureFlowError):
    """Raised when deterministic fingerprint computation encounters invalid parameters."""

    pass
