import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scarlett_monitor.py"
SPEC = importlib.util.spec_from_file_location("scarlett_monitor", MODULE_PATH)
monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(monitor)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
DEMO_STATES = Path("/usr/share/doc/alsa-scarlett-gui/demo")


def fixture_controls():
    return monitor.parse_state_file((FIXTURES / "scarlett-4i4-gen4.state").read_text(encoding="utf-8"))["Gen"]


def enum(value):
    return {"value": value, "min": 0, "max": 0, "db": None, "db_value": None}


def gain(raw, db_value=None):
    return {"value": raw, "min": 0, "max": 184, "db": ("minmax", -80.0, 12.0), "db_value": db_value}


def compact(rows):
    """Rows as 'destination <- via <- sources' strings for readable asserts."""
    lines = []
    for row in rows:
        sources = ", ".join(
            source["label"] + ("" if source["db"] in (None, 0) else f" {source['db']} dB")
            for source in row["sources"]
        )
        if row["off"]:
            lines.append(f"{row['destination']} <- Off")
            continue
        lines.append(f"{row['destination']} <- {row['via'] or '-'} <- {sources}")
    return lines


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



class ControlParsingTests(unittest.TestCase):
    def test_amixer_contents_resolves_enum_items_and_gains(self):
        controls = monitor.parse_amixer_contents((FIXTURES / "amixer-contents.txt").read_text(encoding="utf-8"))
        self.assertEqual(controls["Analogue Output 05 Playback Enum"]["value"], "Mix E")
        self.assertEqual(controls["DSP Input 1 Capture Enum"]["value"], "Analogue 1")
        level = controls["Mix E Input 05 Playback Volume"]
        self.assertEqual(level["value"], 160)
        self.assertEqual(round(monitor.mix_gain_db(level)), 0)

    def test_state_file_matches_live_parser(self):
        live = monitor.parse_amixer_contents((FIXTURES / "amixer-contents.txt").read_text(encoding="utf-8"))
        stored = fixture_controls()
        for name, control in live.items():
            self.assertEqual(stored[name]["value"], control["value"], name)

    def test_linear_gain_scale_reads_unity_as_zero_db(self):
        # The large 4th Gen interfaces expose amplitude-linear mixer gains.
        control = {"value": 8192, "min": 0, "max": 32613, "db": ("linear", -99999.99, 12.0), "db_value": None}
        self.assertEqual(round(monitor.mix_gain_db(control)), 0)

    def test_focusrite_cards_are_found_without_pipewire(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / "cards").write_text(
                " 0 [USB            ]: USB-Audio - Scarlett 18i20 USB\n"
                "                      Focusrite Scarlett 18i20 USB at usb-1, high speed\n"
                " 1 [Generic        ]: HDA-Intel - HD-Audio Generic\n",
                encoding="utf-8",
            )
            for index, (card, usb_id) in enumerate((("USB", "1235:8215"), ("Generic", "1022:15e3"))):
                (root / f"card{index}").mkdir()
                (root / f"card{index}" / "id").write_text(card + "\n", encoding="utf-8")
                (root / f"card{index}" / "usbid").write_text(usb_id + "\n", encoding="utf-8")
            self.assertEqual(monitor.focusrite_cards(root), {"USB": "Scarlett 18i20 USB"})


class RoutingViewTests(unittest.TestCase):
    def test_scarlett_4i4_gen4_routing(self):
        self.assertEqual(compact(monitor.routing_rows(fixture_controls(), "Scarlett 4i4 4th Gen")), [
            "Line 1–2 <- Mix A–B <- PC 1–2",
            "Line 3–4 <- - <- In 1",
            "Phones <- Mix E–F <- In 1 (DSP) -48 dB, PC 1–2",
            "Rec 1–2 <- - <- In 1–2 (DSP)",
            "Rec 3–4 <- - <- In 3–4",
            "Rec 5–6 <- Mix E–F <- In 1 (DSP) -48 dB, PC 1–2",
        ])

    def test_unknown_models_use_generic_output_names(self):
        rows = monitor.routing_rows(fixture_controls(), "Scarlett 4i4 3rd Gen")
        self.assertEqual([row["destination"] for row in rows if row["section"] == "hear"], ["Out 1–2", "Out 3–4", "Out 5–6"])

    def test_large_gen4_control_names_are_understood(self):
        # The FCP driver names controls without "Output"/"Input".
        controls = {
            "Analogue 1 Playback Enum": enum("Mix A"),
            "Analogue 2 Playback Enum": enum("Mix B"),
            "Mixer 1 Capture Enum": enum("Analogue 1"),
            "Mixer 2 Capture Enum": enum("PCM 1"),
            "Mixer 3 Capture Enum": enum("PCM 2"),
            "Mix A Input 01 Playback Volume": gain(160),
            "Mix B Input 01 Playback Volume": gain(160),
            "Mix A Input 02 Playback Volume": gain(160),
            "Mix B Input 03 Playback Volume": gain(160),
            "PCM 1 Capture Enum": enum("Analogue 1"),
            "PCM 2 Capture Enum": enum("Analogue 2"),
            "PCM 3 Capture Enum": enum("Off"),
        }
        self.assertEqual(compact(monitor.routing_rows(controls)), [
            "Out 1–2 <- Mix A–B <- In 1, PC 1–2",
            "Rec 1–2 <- - <- In 1–2",
            "Rec 3 <- Off",
        ])

    def test_inputs_shared_by_a_stereo_mix_fold_into_one_range(self):
        controls = {"Analogue Output 01 Playback Enum": enum("Mix A"), "Analogue Output 02 Playback Enum": enum("Mix B")}
        for channel in range(1, 9):
            controls[f"Mixer Input {channel:02d} Capture Enum"] = enum(f"Analogue {channel}")
            controls[f"Mix A Input {channel:02d} Playback Volume"] = gain(160)
            controls[f"Mix B Input {channel:02d} Playback Volume"] = gain(160)
        self.assertEqual(compact(monitor.routing_rows(controls)), ["Out 1–2 <- Mix A–B <- In 1–8"])

    def test_unmatched_mixes_stay_on_separate_rows(self):
        controls = {
            "Analogue Output 01 Playback Enum": enum("Mix A"),
            "Analogue Output 02 Playback Enum": enum("Mix B"),
            "Mixer Input 01 Capture Enum": enum("Analogue 5"),
            "Mixer Input 02 Capture Enum": enum("S/PDIF 2"),
            "Mix A Input 01 Playback Volume": gain(160),
            "Mix B Input 02 Playback Volume": gain(150),
        }
        self.assertEqual(compact(monitor.routing_rows(controls)), [
            "Out 1 <- Mix A <- In 5",
            "Out 2 <- Mix B <- S/PDIF 2 -5 dB",
        ])

    def test_interfaces_without_routing_report_no_rows(self):
        controls = {"Direct Monitor Playback Enum": enum("Mono"), "Line In 1 Level Capture Enum": enum("Line")}
        self.assertEqual(monitor.routing_rows(controls), [])
        self.assertEqual(monitor.routing_signature(controls), {})

    @unittest.skipUnless(DEMO_STATES.is_dir(), "alsa-scarlett-gui demo files are not installed")
    def test_every_mixer_app_demo_interface_renders(self):
        no_routing = {"Scarlett Gen 3 Solo", "Scarlett Gen 3 2i2"}
        for path in sorted(DEMO_STATES.glob("*.state")):
            for card, controls in monitor.parse_state_file(path.read_text(encoding="utf-8")).items():
                with self.subTest(model=path.stem, card=card):
                    rows = monitor.routing_rows(controls, path.stem)
                    if path.stem in no_routing or path.stem.startswith("Scarlett Gen 1"):
                        self.assertEqual(rows, [])
                        continue
                    self.assertTrue(rows)
                    for row in rows:
                        self.assertTrue(row["destination"])
                        for source in row["sources"]:
                            self.assertTrue(source["label"])
                            self.assertTrue(source["db"] is None or -100 <= source["db"] <= 12, source)


class RouteEditingTests(unittest.TestCase):
    def rows(self):
        return {row["key"]: row for row in monitor.routing_rows(fixture_controls(), "Scarlett 4i4 4th Gen")}

    def test_rows_offer_aligned_stereo_choices_with_the_current_one_marked(self):
        phones = self.rows()["out:5:2"]
        labels = [choice["label"] for choice in phones["choices"]]
        self.assertEqual(labels, [
            "PC 1–2", "PC 3–4", "PC 5–6", "In 1–2", "In 3–4", "In 1–2 (DSP)", "Mix A–B", "Mix C–D", "Mix E–F", "Off",
        ])
        self.assertEqual([choice["key"] for choice in phones["choices"] if choice["current"]], ["mix:5:2"])

    def test_a_mono_source_on_both_sides_stays_selectable(self):
        line = self.rows()["out:3:2"]
        self.assertEqual(line["current"], "in:1:1")
        self.assertEqual(
            line["choices"][0],
            {"key": "in:1:1", "label": "In 1 (mono)", "kind": "in", "group": "Inputs", "current": True},
        )

    def test_recording_the_headphone_mix_refers_back_to_it(self):
        rows = self.rows()
        self.assertEqual(rows["rec:5:2"]["same_as"], "Phones")
        self.assertEqual(rows["out:5:2"]["same_as"], "")

    def test_chips_explain_themselves(self):
        phones = self.rows()["out:5:2"]
        self.assertEqual(phones["destination_hint"], "Headphone output")
        self.assertIn("blends its sources", phones["via_hint"])
        self.assertEqual(
            phones["sources"][0]["hint"],
            "Input 1 on the interface, after the interface's input processing (DSP), mixed in at −48 dB",
        )
        self.assertEqual(phones["sources"][1]["hint"], "Audio your computer plays on channels 1–2")

    def set_route(self, row, choice):
        commands = self.commands = []
        with patch.object(monitor, "require_card", return_value="Gen"), \
             patch.object(monitor, "read_controls", return_value=fixture_controls()), \
             patch.object(monitor, "model_name", return_value="Scarlett 4i4 4th Gen"), \
             patch.object(monitor, "run", side_effect=lambda command: commands.append(command) or ""), \
             patch.object(monitor, "status", return_value={"ok": True}):
            result = monitor.set_route(row, choice)
        return commands, result

    def items(self, name):
        return fixture_controls()[name]["items"]

    def test_stereo_choice_sets_both_channels_by_item_index(self):
        commands, result = self.set_route("out:5:2", "pc:1:2")
        left = self.items("Analogue Output 05 Playback Enum").index("PCM 1")
        right = self.items("Analogue Output 06 Playback Enum").index("PCM 2")
        self.assertEqual([command[-1] for command in commands], [str(left), str(right)])
        self.assertTrue(all(command[:5] == ["amixer", "-q", "-c", "Gen", "cset"] for command in commands))
        self.assertEqual(result["notice"], "Phones now plays PC 1–2")

    def test_mono_and_off_choices(self):
        commands, _ = self.set_route("out:3:2", "in:2:1")
        index = str(self.items("Analogue Output 03 Playback Enum").index("Analogue 2"))
        self.assertEqual([command[-1] for command in commands], [index, index])
        commands, result = self.set_route("rec:3:2", "off")
        self.assertEqual([command[-1] for command in commands], ["0", "0"])
        self.assertEqual(result["notice"], "Rec 3–4 is now off")

    def test_invalid_routes_write_nothing(self):
        for row, choice in (
            ("out:9:2", "pc:1:2"),     # no such output
            ("out:5:2", "pc:1:3"),     # width mismatch
            ("out:5:2", "mix:7:2"),    # Mix G–H does not exist on a 4i4
            ("out:5:2", "pc:1:2;rm"),  # not a choice key
            ("bogus", "off"),
        ):
            with self.subTest(row=row, choice=choice):
                with self.assertRaises(monitor.MonitorError):
                    self.set_route(row, choice)
                self.assertEqual(self.commands, [])


class ConfigTests(unittest.TestCase):
    def test_routing_view_is_remembered_and_validated(self):
        with tempfile.TemporaryDirectory() as config, patch.dict(os.environ, {"XDG_CONFIG_HOME": config}):
            self.assertEqual(monitor.load_config()["routing_view"], "compact")
            with patch.object(monitor, "status", return_value={"ok": True}):
                monitor.dispatch(["routing-view", "all"])
            self.assertEqual(monitor.load_config()["routing_view"], "all")
            monitor.config_path().write_text('{"routing_view": "huge", "last_monitor_volume": 40}', encoding="utf-8")
            self.assertEqual(monitor.load_config(), {"version": 1, "last_monitor_volume": 40, "routing_view": "compact"})


class PresetTests(unittest.TestCase):
    def setUp(self):
        self.config = tempfile.TemporaryDirectory()
        self.addCleanup(self.config.cleanup)
        patcher = patch.dict(os.environ, {"XDG_CONFIG_HOME": self.config.name, "XDG_RUNTIME_DIR": self.config.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        monitor.presets_dir().mkdir(parents=True)

    def write_preset(self, name, card="Gen", text=None):
        text = text or (FIXTURES / "scarlett-4i4-gen4.state").read_text(encoding="utf-8")
        text = text.replace("state.Gen {", f"state.{card} {{", 1)
        (monitor.presets_dir() / f"{name}.state").write_text(text, encoding="utf-8")

    def test_preset_names_cannot_escape_the_presets_folder(self):
        for name in ("../evil", "a/b", "", ".hidden", "x" * 60, "trailing."):
            with self.subTest(name=name), self.assertRaises(monitor.MonitorError):
                monitor.preset_path(name)
        self.assertEqual(monitor.preset_path("Streaming 2").name, "Streaming 2.state")

    def test_matching_preset_is_marked_active(self):
        self.write_preset("Current")
        changed = (FIXTURES / "scarlett-4i4-gen4.state").read_text(encoding="utf-8").replace(
            "name 'PCM 03 Capture Enum'\n\t\tvalue 'Analogue 3'", "name 'PCM 03 Capture Enum'\n\t\tvalue Off"
        )
        self.write_preset("Changed", text=changed)
        presets = monitor.list_presets("Gen", fixture_controls())
        self.assertEqual(
            [(item["name"], item["active"], item["compatible"]) for item in presets],
            [("Changed", False, True), ("Current", True, True)],
        )

    def test_preset_from_another_card_id_is_retargeted(self):
        self.write_preset("Other machine", card="USB_1")
        restored = []

        def fake_run(command):
            restored.append((command, Path(command[3]).read_text(encoding="utf-8").splitlines()[0]))
            return ""

        with patch.object(monitor, "require_card", return_value="Gen"), \
             patch.object(monitor, "read_controls", return_value=fixture_controls()), \
             patch.object(monitor, "run", side_effect=fake_run), \
             patch.object(monitor, "status", return_value={"ok": True}):
            monitor.apply_preset("Other machine")
        command, first_line = restored[0]
        self.assertEqual(command[:3], ["alsactl", "-I", "-f"])
        self.assertEqual(command[4:], ["restore", "Gen"])
        self.assertEqual(first_line, "state.Gen {")
        self.assertFalse(Path(command[3]).exists(), "temporary preset copy should be removed")

    def test_ambiguous_multi_card_preset_is_refused(self):
        text = (FIXTURES / "scarlett-4i4-gen4.state").read_text(encoding="utf-8")
        self.write_preset("Two cards", text=text.replace("state.Gen {", "state.USB {", 1) + text.replace(
            "state.Gen {", "state.USB_1 {", 1))
        with patch.object(monitor, "require_card", return_value="Gen"), \
             patch.object(monitor, "read_controls", return_value=fixture_controls()), \
             patch.object(monitor, "run") as run:
            with self.assertRaises(monitor.MonitorError):
                monitor.apply_preset("Two cards")
        run.assert_not_called()

    def test_preset_for_a_different_model_is_refused(self):
        self.write_preset("Gen 1", text="state.USB {\n\tcontrol.1 {\n\t\tiface MIXER\n"
                          "\t\tname 'Master 1L (Monitor) Source Playback Enum'\n\t\tvalue 'PCM 1'\n\t}\n}\n")
        with patch.object(monitor, "require_card", return_value="Gen"), \
             patch.object(monitor, "read_controls", return_value=fixture_controls()), \
             patch.object(monitor, "run") as run:
            with self.assertRaises(monitor.MonitorError):
                monitor.apply_preset("Gen 1")
        run.assert_not_called()

    def test_delete_removes_only_the_named_preset(self):
        self.write_preset("Keep")
        self.write_preset("Remove")
        with patch.object(monitor, "status", return_value={"ok": True}):
            result = monitor.delete_preset("Remove")
            with self.assertRaises(monitor.MonitorError):
                monitor.delete_preset("Remove")
            with self.assertRaises(monitor.MonitorError):
                monitor.delete_preset("../scarlett-mic-control")
        self.assertEqual(result["notice"], "Deleted Remove")
        self.assertEqual(sorted(path.stem for path in monitor.presets_dir().iterdir()), ["Keep"])

    def test_saving_never_overwrites_an_existing_preset(self):
        self.write_preset("Keep")
        with patch.object(monitor, "require_card", return_value="Gen"), \
             patch.object(monitor, "run") as run:
            with self.assertRaises(monitor.MonitorError):
                monitor.save_preset("Keep")
        run.assert_not_called()


class MixerAppTests(unittest.TestCase):
    def test_status_reports_whether_the_mixer_app_is_installed(self):
        for found in (True, False):
            with self.subTest(found=found), \
                 patch.object(monitor, "scarlett_sources", return_value=[]), \
                 patch.object(monitor, "candidate_cards", return_value=[]), \
                 patch.object(monitor.shutil, "which", side_effect=lambda name: "/usr/bin/x" if found else None):
                result = monitor.status()
            self.assertEqual(result["mixer_app_installed"], found)
            self.assertFalse(result["routing_available"])


if __name__ == "__main__":
    unittest.main()
