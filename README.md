# appdaemon_common

Common base classes and helpers for AppDaemon apps.

## Features
- Ordered init flow via `@init_step`
- Standard health entity and heartbeat logging
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
  output_entity: input_boolean.heating_needed
  threshold: 23.5
  invert: false
  heartbeat_s: 600
```

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
