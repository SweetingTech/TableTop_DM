class KernelError(Exception):
    """Base error for deterministic kernel failures."""


class AuthorizationDenied(KernelError):
    pass


class WorldClockPaused(AuthorizationDenied):
    """Expected suspension; runners must preserve the character controller's budget."""


class BodySleeping(AuthorizationDenied):
    """Expected bodily suspension; autonomous actions wait without spending a control step."""


class BodyIncapacitated(ValueError):
    """Expected voluntary-action suspension, not a stand-in policy failure."""


class DuplicateCommand(KernelError):
    pass


class UnknownCommand(KernelError):
    pass


class BranchIsolationError(KernelError):
    pass
