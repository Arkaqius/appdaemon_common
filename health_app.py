"""Health-aware base class for AppDaemon apps."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from typing import Any, Callable, Dict, Optional

from .app_base import AppBase

_MQTT_ID_RE = re.compile(r"[^A-Za-z0-9_]+")


def _mqtt_id(value: Any, *, fallback: str) -> str:
    """Return a Home Assistant MQTT discovery-safe id."""
    raw = str(value or "").strip()
    text = _MQTT_ID_RE.sub("_", raw).strip("_").lower()
    return text or fallback


def _topic_join(*parts: Any) -> str:
    """Join MQTT topic fragments without duplicate slashes."""
    return "/".join(str(part).strip("/") for part in parts if str(part).strip("/"))


def _json_payload(payload: Any) -> str:
    """Serialize MQTT JSON consistently for deterministic discovery payloads."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "on", "yes", "1"):
            return True
        if normalized in ("false", "off", "no", "0"):
            return False
    return default


class HealthAppBase(AppBase):
    """App base with standardized MQTT discovery health sensor and heartbeat."""

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
        self._health_object_id = self._resolve_health_object_id()
        self._health_unique_id = self._resolve_health_unique_id()
        self._health_name = self._resolve_health_name()
        self._health_state_topic = self._resolve_health_state_topic()
        self._health_availability_topic = self._resolve_health_availability_topic()
        self._health_config_topic = self._resolve_health_config_topic()
        self._health_mqtt_api = self._resolve_mqtt_api()
        self._health_mqtt_qos = self._resolve_health_mqtt_qos()
        self._health_retain_state = self._resolve_health_retain_state()
        self._app_started_at = _dt.datetime.now(_dt.timezone.utc)
        self._heartbeat_message_cb: Optional[Callable[[], Optional[str]]] = None

        # Initialize MQTT discovery and health state early.
        self._publish_health_discovery()
        self._publish_health_availability("online")
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
                entity_id = str(value)
                if not entity_id.startswith("sensor."):
                    raise ValueError("health_entity_id must use the sensor domain for MQTT discovery")
                return entity_id
        return f"sensor.app_{_mqtt_id(self.name, fallback='app')}_health"

    def _resolve_health_object_id(self) -> str:
        return _mqtt_id(self._health_entity_id.split(".", 1)[-1], fallback="app_health")

    def _resolve_health_unique_id(self) -> str:
        if hasattr(self, "args"):
            value = self.args.get("health_unique_id")
            if value:
                return _mqtt_id(value, fallback=self._health_object_id)
        return f"appdaemon_common_{_mqtt_id(self.name, fallback='app')}_health"

    def _resolve_health_name(self) -> str:
        if hasattr(self, "args"):
            value = self.args.get("health_name")
            if value:
                return str(value)
        return f"{self.name} Health"

    def _resolve_mqtt_plugin_name(self) -> str:
        if hasattr(self, "args"):
            value = self.args.get("mqtt_plugin") or self.args.get("mqtt_plugin_name")
            if value:
                return str(value)
        return "MQTT"

    def _resolve_mqtt_api(self) -> Any:
        plugin_name = self._resolve_mqtt_plugin_name()
        if not hasattr(self, "get_plugin_api"):
            raise RuntimeError("HealthAppBase requires AppDaemon MQTT plugin support")

        mqtt_api = self.get_plugin_api(plugin_name)
        if mqtt_api is None:
            raise RuntimeError(
                f"HealthAppBase requires an AppDaemon MQTT plugin named '{plugin_name}'"
            )
        if not hasattr(mqtt_api, "mqtt_publish"):
            raise RuntimeError(f"Plugin '{plugin_name}' does not provide mqtt_publish()")
        return mqtt_api

    def _resolve_mqtt_discovery_prefix(self) -> str:
        if hasattr(self, "args"):
            value = self.args.get("mqtt_discovery_prefix")
            if value:
                return str(value).strip("/")
        return "homeassistant"

    def _resolve_mqtt_base_topic(self) -> str:
        if hasattr(self, "args"):
            value = self.args.get("mqtt_base_topic") or self.args.get("health_base_topic")
            if value:
                return str(value).strip("/")
        return _topic_join("appdaemon", _mqtt_id(self.name, fallback="app"))

    def _resolve_health_state_topic(self) -> str:
        if hasattr(self, "args"):
            value = self.args.get("health_state_topic")
            if value:
                return str(value).strip("/")
        return _topic_join(self._resolve_mqtt_base_topic(), "health", "state")

    def _resolve_health_availability_topic(self) -> str:
        if hasattr(self, "args"):
            value = self.args.get("health_availability_topic")
            if value:
                return str(value).strip("/")
        return _topic_join(self._resolve_mqtt_base_topic(), "availability")

    def _resolve_health_config_topic(self) -> str:
        return _topic_join(
            self._resolve_mqtt_discovery_prefix(),
            "sensor",
            self._health_object_id,
            "config",
        )

    def _resolve_health_mqtt_qos(self) -> int:
        if hasattr(self, "args"):
            value = self.args.get("health_mqtt_qos", self.args.get("mqtt_qos", 0))
            try:
                return int(value)
            except (TypeError, ValueError):
                self.log(f"Invalid health_mqtt_qos={value!r}; using 0", level="WARNING")
        return 0

    def _resolve_health_retain_state(self) -> bool:
        if hasattr(self, "args"):
            value = self.args.get("health_retain_state")
            return _as_bool(value, default=False)
        return False

    def _health_device_info(self) -> Dict[str, Any]:
        slug = _mqtt_id(self.name, fallback="app")
        return {
            "identifiers": [f"appdaemon_app_{slug}"],
            "manufacturer": "AppDaemon",
            "model": "AppDaemon App",
            "name": f"AppDaemon {self.name}",
        }

    def _health_discovery_payload(self) -> Dict[str, Any]:
        return {
            "availability_topic": self._health_availability_topic,
            "default_entity_id": self._health_entity_id,
            "device": self._health_device_info(),
            "icon": "mdi:heart-pulse",
            "json_attributes_template": "{{ value_json.attributes | tojson }}",
            "json_attributes_topic": self._health_state_topic,
            "name": self._health_name,
            "payload_available": "online",
            "payload_not_available": "offline",
            "state_topic": self._health_state_topic,
            "unique_id": self._health_unique_id,
            "value_template": "{{ value_json.state }}",
        }

    def _publish_health_discovery(self) -> None:
        self._health_mqtt_api.mqtt_publish(
            self._health_config_topic,
            _json_payload(self._health_discovery_payload()),
            qos=self._health_mqtt_qos,
            retain=True,
        )

    def _publish_health_availability(self, payload: str) -> None:
        self._health_mqtt_api.mqtt_publish(
            self._health_availability_topic,
            payload,
            qos=self._health_mqtt_qos,
            retain=True,
        )

    def _publish_health_state(self, state: str, attributes: Dict[str, Any]) -> None:
        payload = {
            "attributes": attributes,
            "state": state,
        }
        self._health_mqtt_api.mqtt_publish(
            self._health_state_topic,
            _json_payload(payload),
            qos=self._health_mqtt_qos,
            retain=self._health_retain_state,
        )

    def set_health(self, state: str, **attrs: Any) -> None:
        """Set health state and publish the MQTT health sensor payload."""
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

        self._publish_health_state(state, merged)

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

    def terminate(self) -> None:
        """Mark the MQTT health sensor unavailable when AppDaemon stops the app."""
        try:
            self._publish_health_availability("offline")
        except Exception as exc:  # pragma: no cover - best effort during shutdown
            self.log(f"Failed to publish health availability offline: {exc}", level="WARNING")
