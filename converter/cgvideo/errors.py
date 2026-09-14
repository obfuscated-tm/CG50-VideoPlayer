class ConvertError(Exception):
    """A problem worth showing to the user as a plain sentence (no traceback)."""


class Cancelled(Exception):
    """The user pressed Cancel."""
