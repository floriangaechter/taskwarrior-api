"""Custom exceptions for inky-bridge."""


class InkyBridgeError(Exception):
    """Base exception for inky-bridge errors."""

    pass


class ConfigurationError(InkyBridgeError):
    """Raised when configuration is invalid or missing."""

    pass


class ReplicaError(InkyBridgeError):
    """Raised when replica operations fail."""

    pass


class SyncError(InkyBridgeError):
    """Raised when sync operations fail."""

    pass
