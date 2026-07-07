from __future__ import annotations


class OrganizerException(Exception):
    """Base exception for organizer subsystem."""

    pass


class OrganizerRuleError(OrganizerException):
    """Raised when no valid organization rule can be applied."""

    pass


class OrganizerPreviewError(OrganizerException):
    """Raised when preview planning fails."""

    pass


class OrganizerApplyError(OrganizerException):
    """Raised when move application fails."""

    pass


class OrganizerRollbackError(OrganizerException):
    """Raised when rollback cannot restore a move batch."""

    pass
