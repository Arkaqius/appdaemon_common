# appdaemon_common

Common base classes and helpers for AppDaemon apps.

## Features
- Ordered init flow via `@init_step`
- Standard health sensor via MQTT discovery and heartbeat logging
- Safe callback decorator to isolate errors
- Timer and listener registries with safe-state isolation
- Simple, typed config validation
- State parsing helpers for HA values

## Install
Copy the `appdaemon_common` package into your AppDaemon app directory or add it to your PYTHONPATH.

## Example
See `examples/example_app.py` for a working sample.

Minimal `apps.yaml`:

```yaml
ExampleApp:
  module: example_app
  class: ExampleApp
  input_entity: sensor.some_temperature
  output_entity: switch.some_heater
  threshold: 23.5
  invert: false
  heartbeat_s: 600
  mqtt_plugin: MQTT
```

`HealthAppBase` requires the AppDaemon MQTT plugin because app-owned entities are
exposed to Home Assistant through MQTT discovery:

```yaml
appdaemon:
  plugins:
    HASS:
      type: hass
    MQTT:
      type: mqtt
      namespace: mqtt
      client_host: core-mosquitto
```

The default health entity is discovered as `sensor.app_<app_name>_health`,
where `<app_name>` is slugified for Home Assistant entity IDs.
Discovery is retained on `homeassistant/sensor/<object_id>/config`; runtime state
is published to `appdaemon/<app_name>/health/state`, and app availability to
`appdaemon/<app_name>/availability`.

Useful optional app args:

```yaml
mqtt_plugin: MQTT
mqtt_discovery_prefix: homeassistant
mqtt_base_topic: appdaemon/my_app
health_entity_id: sensor.app_my_app_health
health_name: My App Health
health_retain_state: false
```

Set `health_entity_id` explicitly when existing dashboards or automations already
refer to an older health entity ID.

## Architecture Rules

- Read physical devices and external signals from Home Assistant with
  `get_state`/`listen_state`.
- Expose AppDaemon-owned entities with MQTT discovery, then publish their state
  to app MQTT topics.
- Receive commands for AppDaemon-owned MQTT entities from MQTT command topics.
  Do not listen to the Home Assistant entity state as the command path.
- Do not use Home Assistant helpers as AppDaemon runtime state storage. Helpers
  are acceptable only when they belong to a separate HA-native workflow.
- Apps that expose MQTT entities require the MQTT plugin; do not add optimistic
  `listen_state` fallbacks for those app-owned entities.

## Basic Usage

```python
from appdaemon_common import HealthAppBase, init_step, safe_callback

class MyApp(HealthAppBase):
    @init_step("config")
    def init_config(self) -> None:
        ...

    @safe_callback("on_change")
    def on_change(self, entity, attribute, old, new, kwargs) -> None:
        ...
```

## License
MIT
