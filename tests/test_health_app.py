from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from appdaemon_common.health_app import HealthAppBase


class FakeMqtt:
    def __init__(self) -> None:
        self.published: list[tuple[str, Any, dict[str, Any]]] = []

    def mqtt_publish(self, topic: str, payload: Any = None, **kwargs: Any) -> None:
        self.published.append((topic, payload, kwargs))


class DummyHealthApp(HealthAppBase):
    def __init__(self, *, name: str = "ExampleApp", args: dict[str, Any] | None = None) -> None:
        self.name = name
        self.args = args or {}
        self.logs: list[tuple[str, str]] = []
        self.mqtt = FakeMqtt()
        self.requested_plugin: str | None = None

    def get_plugin_api(self, plugin_name: str) -> FakeMqtt:
        self.requested_plugin = plugin_name
        return self.mqtt

    def log(self, msg: str, level: str = "INFO") -> None:
        self.logs.append((level, msg))


class HealthAppMqttDiscoveryTests(unittest.TestCase):
    def test_initialize_publishes_discovery_availability_and_state(self) -> None:
        app = DummyHealthApp()

        app.initialize()

        discovery_topic, discovery_payload, discovery_kwargs = app.mqtt.published[0]
        self.assertEqual(discovery_topic, "homeassistant/sensor/app_exampleapp_health/config")
        self.assertEqual(discovery_kwargs, {"qos": 0, "retain": True})

        discovery = json.loads(discovery_payload)
        self.assertEqual(discovery["default_entity_id"], "sensor.app_exampleapp_health")
        self.assertEqual(discovery["state_topic"], "appdaemon/exampleapp/health/state")
        self.assertEqual(discovery["availability_topic"], "appdaemon/exampleapp/availability")
        self.assertEqual(discovery["unique_id"], "appdaemon_common_exampleapp_health")
        self.assertEqual(discovery["device"]["identifiers"], ["appdaemon_app_exampleapp"])

        availability_topic, availability_payload, availability_kwargs = app.mqtt.published[1]
        self.assertEqual(availability_topic, "appdaemon/exampleapp/availability")
        self.assertEqual(availability_payload, "online")
        self.assertEqual(availability_kwargs, {"qos": 0, "retain": True})

        state_publishes = [
            item for item in app.mqtt.published if item[0] == "appdaemon/exampleapp/health/state"
        ]
        self.assertEqual(len(state_publishes), 2)
        _, state_payload, state_kwargs = state_publishes[-1]
        state = json.loads(state_payload)
        self.assertEqual(state["state"], "running")
        self.assertEqual(state["attributes"]["app_name"], "ExampleApp")
        self.assertEqual(state["attributes"]["health_state"], "running")
        self.assertEqual(state_kwargs, {"qos": 0, "retain": False})

    def test_custom_health_mqtt_settings(self) -> None:
        app = DummyHealthApp(
            args={
                "health_entity_id": "sensor.demo_health",
                "health_mqtt_qos": 1,
                "health_name": "Demo Health",
                "health_retain_state": "true",
                "mqtt_base_topic": "apps/demo",
                "mqtt_discovery_prefix": "ha",
                "mqtt_plugin": "Mosquitto",
            }
        )

        app.initialize()

        self.assertEqual(app.requested_plugin, "Mosquitto")
        discovery_topic, discovery_payload, _ = app.mqtt.published[0]
        self.assertEqual(discovery_topic, "ha/sensor/demo_health/config")
        discovery = json.loads(discovery_payload)
        self.assertEqual(discovery["name"], "Demo Health")
        self.assertEqual(discovery["state_topic"], "apps/demo/health/state")
        self.assertEqual(discovery["availability_topic"], "apps/demo/availability")

        state_publishes = [item for item in app.mqtt.published if item[0] == "apps/demo/health/state"]
        self.assertEqual(state_publishes[-1][2], {"qos": 1, "retain": True})

    def test_health_entity_id_must_be_sensor(self) -> None:
        app = DummyHealthApp(args={"health_entity_id": "binary_sensor.bad_health"})

        with self.assertRaises(ValueError):
            app.initialize()


if __name__ == "__main__":
    unittest.main()
