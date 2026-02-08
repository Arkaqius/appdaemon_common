"""Simple config validation for AppDaemon apps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Mapping, Optional


class ConfigError(Exception):
    """Raised when configuration is invalid."""


def parse_bool(value: Any) -> bool:
    """Parse a bool-like value or raise ValueError."""
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
    raise ValueError(f"Invalid boolean value: {value!r}")


@dataclass
class Field:
    """Describe a single config field and its validation/coercion."""
    name: str
    py_type: type | tuple[type, ...] = str
    required: bool = False
    default: Any = None
    aliases: Optional[Iterable[str]] = None
    coerce: Optional[Callable[[Any], Any]] = None
    validator: Optional[Callable[[Any], None]] = None


class ConfigSchema:
    def __init__(self, fields: Iterable[Field], *, strict: bool = False) -> None:
        """Create a schema with optional strict key checking."""
        self.fields = {f.name: f for f in fields}
        self.strict = strict

    def validate(
        self,
        args: Mapping[str, Any],
        *,
        log: Optional[Callable[[str], None]] = None,
        context: str = "",
    ) -> Dict[str, Any]:
        """Validate and coerce args into a typed config dict."""
        parsed: Dict[str, Any] = {}
        used_keys: set[str] = set()

        def warn(msg: str) -> None:
            if log:
                log(msg)

        for name, field in self.fields.items():
            raw = None
            if name in args:
                raw = args.get(name)
                used_keys.add(name)
            else:
                for alias in field.aliases or []:
                    if alias in args:
                        raw = args.get(alias)
                        used_keys.add(alias)
                        warn(f"Using legacy arg '{alias}' for '{name}'.")
                        break

            if raw is None:
                if field.required and field.default is None:
                    raise ConfigError(self._fmt_err(f"Missing required arg '{name}'.", context))
                parsed[name] = field.default
                continue

            # Coerce/validate
            try:
                value = self._coerce_value(raw, field)
            except Exception as exc:
                raise ConfigError(self._fmt_err(f"Invalid value for '{name}': {exc}", context)) from exc

            if field.validator is not None:
                try:
                    field.validator(value)
                except Exception as exc:
                    raise ConfigError(self._fmt_err(f"Validation failed for '{name}': {exc}", context)) from exc

            parsed[name] = value

        if self.strict:
            extra = set(args.keys()) - used_keys - set(self.fields.keys())
            if extra:
                raise ConfigError(self._fmt_err(f"Unknown config keys: {sorted(extra)}", context))

        return parsed

    @staticmethod
    def _coerce_value(raw: Any, field: Field) -> Any:
        if field.coerce is not None:
            return field.coerce(raw)

        # Default coercions
        if field.py_type is bool:
            return parse_bool(raw)
        if field.py_type is int:
            return int(raw)
        if field.py_type is float:
            return float(raw)
        if field.py_type is str:
            return str(raw)

        # If py_type is a tuple or other, just type-check
        if not isinstance(raw, field.py_type):
            raise ValueError(f"Expected {field.py_type}, got {type(raw)}")
        return raw

    @staticmethod
    def _fmt_err(msg: str, context: str) -> str:
        if context:
            return f"[{context}] {msg}"
        return msg
