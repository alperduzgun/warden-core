"""
Package Manager Exceptions.

Custom exception hierarchy for package management operations.
Enables fail-fast error handling and precise error reporting.
"""


class WardenPackageError(Exception):
    """Base exception for package management operations."""
    pass


class LockfileCorruptionError(WardenPackageError):
    """Lockfile is corrupt or has invalid schema."""
    pass


class GitRefResolutionError(WardenPackageError):
    """Cannot resolve Git ref to exact commit hash."""
    pass


class IntegrityCheckFailure(WardenPackageError):
    """Frame drift detected and repair failed."""
    pass


class PartialInstallError(WardenPackageError):
    """Installation failed partway through, transaction aborted."""
    pass
