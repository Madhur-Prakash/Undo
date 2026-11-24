"""Time helpers. The database stores naive UTC datetimes; the outside world sees aware ones."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from undo_core.utils.errors import InvalidInputError


def utcnow() -> datetime:
    """Naive UTC timestamp for database storage."""
    return datetime.now(UTC).replace(tzinfo=None)


def to_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def to_db(value: datetime) -> datetime:
    """Convert any datetime to naive UTC. Naive input is interpreted as local time."""
    if value.tzinfo is None:
        value = value.astimezone()  # interpret as local time
    return value.astimezone(UTC).replace(tzinfo=None)


_RELATIVE_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_timestamp(text: str) -> datetime:
    """Parse a user supplied point in time into naive UTC.

    Accepts ISO-8601 (``2024-05-01``, ``2024-05-01T13:00``, with or without an
    offset; naive values are local time) and relative forms such as ``2h``,
    ``3d ago``, ``30m``.
    """
    raw = text.strip().lower()
    if raw.endswith(" ago"):
        raw = raw[:-4].strip()
    if raw == "now":
        return utcnow()
    if len(raw) >= 2 and raw[-1] in _RELATIVE_UNITS and raw[:-1].replace(".", "", 1).isdigit():
        seconds = float(raw[:-1]) * _RELATIVE_UNITS[raw[-1]]
        return utcnow() - timedelta(seconds=seconds)
    try:
        parsed = datetime.fromisoformat(
            text.strip().replace(" ", "T", 1) if " " in text.strip() else text.strip()
        )
    except ValueError as exc:
        raise InvalidInputError(
            f"Cannot parse time {text!r}. Use ISO format (2024-05-01T13:00) or relative (2h, 3d)."
        ) from exc
    return to_db(parsed)
