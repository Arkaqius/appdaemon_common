"""State parsing and validation helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


class StateUtils:
    """Helpers for validating and converting Home Assistant state values."""

    INVALID_STATES = {
        None,
        "",
        "unknown",
        "unavailable",
        "Unavailable",
        "none",
        "None",
    }

    @staticmethod
    def is_valid(value: Any) -> bool:
        """Return True when a state value is usable."""
        if value in StateUtils.INVALID_STATES:
            return False
        if isinstance(value, str) and value.strip() in StateUtils.INVALID_STATES:
            return False
        return True

    @staticmethod
    def normalize(value: Any) -> Any:
        """Normalize string values by stripping whitespace."""
        if isinstance(value, str):
            return value.strip()
        return value

    @staticmethod
    def to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
        """Convert a value to float or return default when invalid."""
        if not StateUtils.is_valid(value):
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def to_int(value: Any, default: Optional[int] = None) -> Optional[int]:
        """Convert a value to int or return default when invalid."""
        if not StateUtils.is_valid(value):
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def parse_iso_datetime(value: Any, default_tz: Optional[Any] = None) -> Optional[datetime]:
        """Parse ISO-8601 datetime values and ensure timezone awareness."""
        if value is None:
            return None
        raw = str(value).strip()
        if not raw or raw.lower() in ("unknown", "unavailable", "none"):
            return None

        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"

        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            for fmt in (
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%d %H:%M:%S%z",
                "%Y-%m-%d %H:%M:%S",
            ):
                try:
                    dt = datetime.strptime(raw, fmt)
                    break
                except ValueError:
                    dt = None
            if dt is None:
                return None

        if dt.tzinfo is None:
            if default_tz is None:
                default_tz = datetime.now().astimezone().tzinfo
            dt = dt.replace(tzinfo=default_tz)
        return dt

    @staticmethod
    def as_bool(value: Any, default: Optional[bool] = None) -> Optional[bool]:
        """Convert common HA boolean-like strings to bool."""
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ("true", "on", "yes", "1"):
                return True
            if v in ("false", "off", "no", "0"):
                return False
        return default
