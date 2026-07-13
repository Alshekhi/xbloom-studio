"""xbloom-py exception hierarchy."""


class XBloomError(Exception):
    """Base class for all xbloom-py errors."""


class XBloomAPIError(XBloomError):
    """API-level failure from the xBloom share endpoint.

    Two call shapes accepted for ergonomics:
        XBloomAPIError(status: int, message: str)  — HTTP error
        XBloomAPIError(message: str)               — application-level error
    """

    def __init__(self, *args: object) -> None:
        if len(args) == 2 and isinstance(args[0], int):
            self.status, message = args  # type: ignore[assignment]
            super().__init__(f"HTTP {self.status}: {message}")
        elif len(args) == 1:
            self.status = 0
            super().__init__(str(args[0]))
        else:
            self.status = 0
            super().__init__(", ".join(str(a) for a in args))
