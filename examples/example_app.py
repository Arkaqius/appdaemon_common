"""Example AppDaemon app using appdaemon_common helpers.

Sample app config (apps.yaml):

ExampleApp:
  module: example_app
  class: ExampleApp
  input_entity: sensor.some_temperature
  output_entity: switch.some_heater
  threshold: 23.5
  invert: false
  heartbeat_s: 600
  mqtt_plugin: MQTT
"""

from __future__ import annotations

from typing import Any

from appdaemon_common import (
    ConfigError,
    ConfigSchema,
    Field,
    HealthAppBase,
    StateUtils,
    init_step,
    safe_callback,
)


def validate_on_off_output(entity: str) -> None:
    """Require a HA-owned controllable entity, not an AppDaemon-created state."""
    if not entity.startswith(("switch.", "light.")):
        raise ValueError("output_entity must be a HA-owned switch.* or light.* entity")


class ExampleApp(HealthAppBase):
    """Minimal example showing HealthAppBase, init flow, config validation, and safe callbacks."""

    def handle_init_exception(self, exc: Exception, step_name: str | None = None) -> None:
        """Treat config errors as faulted health without stopping heartbeat."""
        if isinstance(exc, ConfigError):
            self.log(f"Invalid configuration: {exc}", level="ERROR")
            self.mark_faulted(exc)
            return
        super().handle_init_exception(exc, step_name=step_name)

    @init_step("config")
    def init_config(self) -> None:
        """Load and validate app configuration."""
        schema = ConfigSchema(
            fields=[
                Field("input_entity", str, required=True),
                Field("output_entity", str, required=True, validator=validate_on_off_output),
                Field("threshold", float, default=23.0),
                Field("invert", bool, default=False),
                Field("heartbeat_s", int, default=600),
            ]
        )
        self.cfg = schema.validate(self.args, log=self.log, context=self.name)
        self.update_health_attrs(config_hash=self.compute_config_hash(self.cfg))

    @init_step("entities")
    def init_entities(self) -> None:
        """Initialize internal runtime state."""
        self._last_value: float | None = None

    @init_step("listeners")
    def init_listeners(self) -> None:
        """Register state listeners."""
        self.listen_state_named("input_change", self.on_input_change, self.cfg["input_entity"])

    @init_step("timers")
    def init_timers(self) -> None:
        """Start background timers such as the heartbeat."""
        self.start_heartbeat(self.cfg["heartbeat_s"])

    @safe_callback("on_input_change")
    def on_input_change(
        self,
        entity: str,
        attribute: str,
        old: Any,
        new: Any,
        kwargs: dict,
    ) -> None:
        """Handle input entity changes and update the output entity."""
        value = StateUtils.to_float(new)
        if value is None:
            self.log(f"Ignored invalid state for {entity}: {new!r}", level="DEBUG")
            return

        threshold = self.cfg["threshold"]
        should_on = value >= threshold
        if self.cfg["invert"]:
            should_on = not should_on

        self._set_output_state(should_on)
        self._last_value = value
        self.update_health_attrs(last_value=value)

    def _set_output_state(self, on: bool) -> None:
        entity = self.cfg["output_entity"]
        if on:
            self.turn_on(entity)
        else:
            self.turn_off(entity)

    def heartbeat_message(self) -> str | None:
        """Append the last input value to the heartbeat log line."""
        if self._last_value is None:
            return None
        return f"last_value={self._last_value}"

    def isolate_app(self, reason: str = "manual_isolation") -> None:
        """
        Example method showing how to isolate the app on demand.

        This cancels listeners and timers, but preserves the heartbeat
        so the health entity still updates.
        """
        self.enter_safe_state(reason, stop_timers=True, stop_listeners=True)
