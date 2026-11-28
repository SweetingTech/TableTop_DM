class KernelError(Exception):
    """Base error for deterministic kernel failures."""


class AuthorizationDenied(KernelError):
    pass


class WorldClockPaused(AuthorizationDenied):
    """Expected suspension; runners must preserve the character controller's budget."""


class BranchCheckpointHeld(WorldClockPaused):
    """The branch is paused at an operator checkpoint boundary."""


class RestoredCampaignPaused(WorldClockPaused):
    """The restored run is waiting for its explicit resume operation."""


class BodySleeping(AuthorizationDenied):
    """Expected bodily suspension; autonomous actions wait without spending a control step."""


class BodyIncapacitated(ValueError):
    """Expected voluntary-action suspension, not a stand-in policy failure."""


class BodyActionPending(ValueError):
    """Expected shared-clock readiness wait, preserving the controller's budgets."""


class BodyOutsideRelevance(BodyActionPending):
    """An offscreen NPC is following its background routine."""


class ActionRejectedAtRevision(ValueError):
    """An autonomous action failed validation against this committed branch revision."""

    def __init__(self, revision: int) -> None:
        super().__init__("character action rejected")
        self.revision = revision


class DuplicateCommand(KernelError):
    pass


class UnknownCommand(KernelError):
    pass


class BranchIsolationError(KernelError):
    pass
