"""Stable failures shared by workspace storage components."""


class WorkspaceError(Exception):
    """A stable, user-facing workspace failure."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
