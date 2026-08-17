class KernelError(Exception):
    """Base error for deterministic kernel failures."""


class AuthorizationDenied(KernelError):
    pass


class DuplicateCommand(KernelError):
    pass


class UnknownCommand(KernelError):
    pass


class BranchIsolationError(KernelError):
    pass
