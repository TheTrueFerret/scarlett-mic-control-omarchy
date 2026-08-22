import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scarlett_monitor.py"
SPEC = importlib.util.spec_from_file_location("scarlett_monitor", MODULE_PATH)
monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(monitor)


def source(name, description, muted=False, card="Gen"):
    return {
        "name": name,
        "description": description,
        "mute": muted,
        "properties": {
            "alsa.id": card,
            "device.description": description,
        },
    }


class ScarlettDiscoveryTests(unittest.TestCase):
    def test_recognizes_scarlett_by_pipewire_metadata(self):
        self.assertTrue(monitor.is_scarlett_source(source("input.1", "Scarlett 2i2 4th Gen")))
        self.assertFalse(monitor.is_scarlett_source(source("input.2", "Built-in Microphone")))

    def test_prefers_default_scarlett_source(self):
        first = source("scarlett.first", "Scarlett Solo")
        default = source("scarlett.default", "Scarlett 4i4", muted=True)
        with patch.object(monitor, "scarlett_sources", return_value=[first, default]), \
             patch.object(monitor, "run", return_value="scarlett.default\n"):
            result = monitor.find_scarlett_mic()
        self.assertEqual(result["name"], "scarlett.default")
        self.assertTrue(result["muted"])


class ScarlettControlTests(unittest.TestCase):
    def test_capture_toggle_targets_discovered_scarlett(self):
        mic = {"name": "scarlett.input", "label": "Scarlett", "muted": False}
        calls = []
        with patch.object(monitor, "find_scarlett_mic", return_value=mic), \
             patch.object(monitor, "run", side_effect=lambda command: calls.append(command) or ""), \
             patch.object(monitor, "status", return_value={"ok": True}):
            monitor.toggle_mic()
        self.assertEqual(calls, [["pactl", "set-source-mute", "scarlett.input", "toggle"]])

    def test_monitor_toggle_remembers_nonzero_level(self):
        hardware = {"card": "Gen", "label": "Scarlett", "left": 160, "right": 160}
        config = {"version": 1, "last_monitor_volume": 75}
        writes = []
        with patch.object(monitor, "find_hardware_monitor", return_value=hardware), \
             patch.object(monitor, "save_config"), \
             patch.object(monitor, "set_raw_monitor_level", side_effect=lambda card, value: writes.append((card, value))), \
             patch.object(monitor, "status", return_value={"ok": True}):
            monitor.toggle_monitor(config)
        self.assertEqual(config["last_monitor_volume"], 100)
        self.assertEqual(writes, [("Gen", 0)])

    def test_monitor_volume_is_clamped_to_unity(self):
        hardware = {"card": "Gen", "label": "Scarlett", "left": 0, "right": 0}
        config = {"version": 1, "last_monitor_volume": 75}
        writes = []
        with patch.object(monitor, "find_hardware_monitor", return_value=hardware), \
             patch.object(monitor, "save_config"), \
             patch.object(monitor, "set_raw_monitor_level", side_effect=lambda card, value: writes.append((card, value))), \
             patch.object(monitor, "status", return_value={"ok": True}):
            monitor.set_monitor_volume(config, 150)
        self.assertEqual(config["last_monitor_volume"], 100)
        self.assertEqual(writes, [("Gen", 160)])


if __name__ == "__main__":
    unittest.main()
