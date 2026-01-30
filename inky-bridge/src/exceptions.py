"""Custom exceptions."""

class InkyBridgeError(Exception):
    pass


class ConfigurationError(InkyBridgeError):
    pass


class ReplicaError(InkyBridgeError):
    pass


class SyncError(InkyBridgeError):
    pass
