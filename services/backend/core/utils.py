"""Utility helpers for the Virtual Professor backend."""


def mask_sensitive(value: str, visible_chars: int = 4) -> str:
    """Mask a sensitive string, showing only the last *visible_chars* characters.

    >>> mask_sensitive("sk-abc123")
    '****c123'
    >>> mask_sensitive("a")
    '****'
    >>> mask_sensitive("", visible_chars=4)
    '****'
    """
    if not value:
        return "****"
    if len(value) <= visible_chars:
        return "*" * 4
    return "*" * 4 + value[-visible_chars:]
