class KernelError(Exception):
    """Base error for deterministic kernel failures."""


class AuthorizationDenied(KernelError):
    pass


class WorldClockPaused(AuthorizationDenied):
    """Expected suspension; runners must preserve the character controller's budget."""


class DuplicateCommand(KernelError):
    pass


class UnknownCommand(KernelError):
    pass


class BranchIsolationError(KernelError):
    pass
