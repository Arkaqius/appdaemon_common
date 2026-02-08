"""Health-aware base class for AppDaemon apps."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from typing import Any, Callable, Dict, Optional

from .app_base import AppBase


class HealthAppBase(AppBase):
    """App base with standardized health entity and heartbeat."""

    HEALTH_STATES = {
        "init",
        "running",
        "degraded",
        "faulted",
    }

    def initialize(self) -> None:
        """Initialize health entity and run base initialization."""
        self._health_state = "init"
        self._health_attrs: Dict[str, Any] = {}
        self._health_entity_id = self._resolve_health_entity_id()
        self._app_started_at = _dt.datetime.now(_dt.timezone.utc)
        self._heartbeat_message_cb: Optional[Callable[[], Optional[str]]] = None

        # Initialize health entity early
        self.set_health("init")

        try:
            super().initialize()
            self.mark_running()
        except Exception:
            # AppBase already logged and marked faulted if available
            raise

    # ---- Health entity ----
    def _resolve_health_entity_id(self) -> str:
        # Allow override from app config
        if hasattr(self, "args"):
            value = self.args.get("health_entity_id") or self.args.get("health_entity")
            if value:
                return str(value)
        return f"sensor.app_{self.name}_health"

    def set_health(self, state: str, **attrs: Any) -> None:
        """Set health state and update health entity attributes."""
        if state not in self.HEALTH_STATES:
            self.log(f"Unknown health state '{state}', forcing to 'degraded'", level="WARNING")
            state = "degraded"

        now = _dt.datetime.now(_dt.timezone.utc)
        self._health_state = state

        # Merge attributes, always keep base info
        self._health_attrs.update(attrs)
        base_attrs = {
            "app_name": self.name,
            "health_state": state,
            "uptime_s": int((now - self._app_started_at).total_seconds()),
            "last_state_ts": now.isoformat(),
        }
        merged = {**self._health_attrs, **base_attrs}

        self.set_state(self._health_entity_id, state=state, attributes=merged)

    def update_health_attrs(self, **attrs: Any) -> None:
        """Update health attributes without changing the health state."""
        self._health_attrs.update(attrs)
        # Keep same state, update attributes
        self.set_health(self._health_state)

    def mark_running(self) -> None:
        """Mark health as running and clear last_error."""
        self.set_health("running", last_error=None)

    def mark_degraded(self, error: Any) -> None:
        """Mark health as degraded and store error details."""
        self.set_health("degraded", last_error=str(error), last_error_ts=self._now_iso())

    def mark_faulted(self, error: Any) -> None:
        """Mark health as faulted and store error details."""
        self.set_health("faulted", last_error=str(error), last_error_ts=self._now_iso())

    # ---- Heartbeat ----
    def start_heartbeat(self, interval_s: int = 1800) -> None:
        """Start periodic heartbeat logging and health updates."""
        start = self.datetime() + _dt.timedelta(seconds=interval_s)
        self.schedule_every("heartbeat", start, interval_s, self._heartbeat_tick)

    def _heartbeat_tick(self, _: Any) -> None:
        message = f"Heartbeat: {self.name} running"
        suffix = None
        try:
            if self._heartbeat_message_cb is not None:
                suffix = self._heartbeat_message_cb()
            else:
                suffix = self.heartbeat_message()
        except Exception as exc:
            self.log(f"Heartbeat message callback failed: {exc}", level="WARNING")

        if suffix:
            message = f"{message} | {suffix}"
        self.log(message, level="INFO")
        self.update_health_attrs(last_run_ts=self._now_iso())

    # ---- Helpers ----
    def _now_iso(self) -> str:
        return _dt.datetime.now(_dt.timezone.utc).isoformat()

    def compute_config_hash(self, config: Any) -> str:
        """Compute a stable hash for a config structure."""
        payload = json.dumps(config, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha1(payload).hexdigest()

    def set_heartbeat_message_callback(self, cb: Callable[[], Optional[str]]) -> None:
        """
        Register an app-specific callback used to append heartbeat info.
        The callback should return a short string (or None).
        """
        self._heartbeat_message_cb = cb

    def heartbeat_message(self) -> Optional[str]:
        """
        Optional override point for subclasses. Return a short string
        to append to the heartbeat log line.
        """
        return None
