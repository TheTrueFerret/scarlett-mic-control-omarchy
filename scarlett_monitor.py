#!/usr/bin/env python3
"""Control Scarlett capture mute, hardware monitoring, and routing presets."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


UNITY_LEVEL = 160
LEFT_CONTROL = "Mix E Input 01"
RIGHT_CONTROL = "Mix F Input 01"
FOCUSRITE_USB_VENDOR = "1235"
MIXER_APP = "alsa-scarlett-gui"
PRESET_SUFFIX = ".state"
PRESET_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,47}$")
ROUTING_VIEWS = ("compact", "all")
DEFAULT_CONFIG = {"version": 1, "last_monitor_volume": 75, "routing_view": "compact"}
ROW_KEY = re.compile(r"^(out|spdif|adat|rec):(\d+):(\d+)$")
CHOICE_KEY = re.compile(r"^(?:off|(in|spdif|adat|pc|dsp|mix):(\d+):(\d+))$")

# Routing controls exposed by the scarlett2 kernel driver and by the user-space
# FCP driver of the large 4th Gen interfaces, which drops "Output"/"Input".
DESTINATIONS = (
    (re.compile(r"^Analogue(?: Output)? 0*(\d+) Playback Enum$"), "out"),
    (re.compile(r"^S/PDIF(?: Output)? 0*(\d+) Playback Enum$"), "spdif"),
    (re.compile(r"^ADAT(?: Output)? 0*(\d+) Playback Enum$"), "adat"),
    (re.compile(r"^PCM 0*(\d+) Capture Enum$"), "rec"),
)
MIXER_INPUT = re.compile(r"^Mixer(?: Input)? 0*(\d+) Capture Enum$")
DSP_INPUT = re.compile(r"^DSP Input 0*(\d+) Capture Enum$")
MIX_GAIN = re.compile(r"^Mix ([A-Z]) Input 0*(\d+) Playback Volume$")
SOURCE_ITEM = re.compile(r"^(Analogue|S/PDIF|ADAT|PCM|DSP|Mix) ([A-Z]|\d+)$")
SOURCE_KINDS = {"Analogue": "in", "S/PDIF": "spdif", "ADAT": "adat", "PCM": "pc", "DSP": "dsp", "Mix": "mix"}
SOURCE_NAMES = {"in": "In", "spdif": "S/PDIF", "adat": "ADAT", "pc": "PC", "dsp": "DSP", "mix": "Mix"}
ITEM_NAMES = {kind: item for item, kind in SOURCE_KINDS.items()}
CHOICE_ORDER = ("pc", "in", "dsp", "spdif", "adat", "mix")
CHOICE_GROUPS = {"pc": "Computer", "in": "Inputs", "dsp": "Inputs", "spdif": "Digital", "adat": "Digital", "mix": "Mixes"}
DESTINATION_NAMES = {"out": "Out", "spdif": "S/PDIF Out", "adat": "ADAT Out", "rec": "Rec"}

# Friendly names for output pairs, only where the front panel is known.
OUTPUT_NAMES = {
    "Scarlett 4i4 4th Gen": {(1, 2): "Line 1–2", (3, 4): "Line 3–4", (5, 6): "Phones"},
}


class MonitorError(RuntimeError):
    pass


def config_base() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "omarchy"


def config_path() -> Path:
    return config_base() / "scarlett-mic-control.json"


def presets_dir() -> Path:
    return config_base() / "scarlett-mic-control" / "presets"


def load_config() -> dict[str, Any]:
    try:
        value = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # A missing, unreadable, or hand-edited preferences file must never take
        # the controls down with it; the next successful write replaces it.
        return dict(DEFAULT_CONFIG)
    if not isinstance(value, dict):
        return dict(DEFAULT_CONFIG)
    try:
        volume = int(value.get("last_monitor_volume", 75))
    except (TypeError, ValueError):
        volume = 75
    view = value.get("routing_view")
    return {
        "version": 1,
        "last_monitor_volume": max(1, min(100, volume)),
        "routing_view": view if view in ROUTING_VIEWS else "compact",
    }


def save_config(config: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def run(command: list[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=6, check=False)
    except FileNotFoundError as exc:
        raise MonitorError(f"{command[0]} is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise MonitorError(f"{command[0]} did not respond") from exc
    if result.returncode:
        raise MonitorError((result.stderr or result.stdout).strip() or f"{command[0]} failed")
    return result.stdout


def pactl_json(*args: str) -> Any:
    try:
        return json.loads(run(["pactl", "-f", "json", *args]) or "null")
    except json.JSONDecodeError as exc:
        raise MonitorError("PipeWire returned malformed input data") from exc


def source_properties(source: dict[str, Any]) -> dict[str, Any]:
    properties = source.get("properties")
    return properties if isinstance(properties, dict) else {}


def is_scarlett_source(source: dict[str, Any]) -> bool:
    properties = source_properties(source)
    blob = " ".join((
        str(source.get("name") or ""),
        str(source.get("description") or ""),
        str(properties.get("device.description") or ""),
        str(properties.get("device.product.name") or ""),
    )).lower()
    return "scarlett" in blob


def scarlett_sources() -> list[dict[str, Any]]:
    try:
        sources = pactl_json("list", "sources")
    except MonitorError:
        # Routing and monitoring still work through ALSA when PipeWire is down.
        return []
    if not isinstance(sources, list):
        return []
    return [
        source for source in sources
        if isinstance(source, dict)
        and not str(source.get("name") or "").endswith(".monitor")
        and is_scarlett_source(source)
    ]


def source_label(source: dict[str, Any]) -> str:
    properties = source_properties(source)
    return str(
        properties.get("device.description")
        or properties.get("device.product.name")
        or source.get("description")
        or "Scarlett microphone"
    )


def find_scarlett_mic(sources: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    sources = scarlett_sources() if sources is None else sources
    if not sources:
        return None
    try:
        default_name = run(["pactl", "get-default-source"]).strip()
    except MonitorError:
        default_name = ""
    source = next((item for item in sources if str(item.get("name") or "") == default_name), sources[0])
    return {
        "name": str(source.get("name") or ""),
        "label": source_label(source),
        "muted": bool(source.get("mute")),
        "properties": source_properties(source),
    }


# --- ALSA cards and controls -------------------------------------------------

def focusrite_cards(root: Path = Path("/proc/asound")) -> dict[str, str]:
    """Map ALSA card ids of connected Focusrite USB interfaces to model names."""
    models: dict[str, str] = {}
    try:
        for line in (root / "cards").read_text(encoding="utf-8").splitlines():
            match = re.match(r"\s*\d+\s+\[(\S+)\s*\]:\s*\S+\s+-\s+(.+)$", line)
            if match:
                models[match.group(1)] = match.group(2).strip()
    except OSError:
        pass
    cards: dict[str, str] = {}
    for entry in sorted(root.glob("card[0-9]*")):
        try:
            usb_id = (entry / "usbid").read_text(encoding="utf-8").strip().lower()
            card = (entry / "id").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if usb_id.startswith(FOCUSRITE_USB_VENDOR + ":") and card:
            cards[card] = models.get(card, card)
    return cards


def candidate_cards(sources: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Scarlett cards as (card id, label), PipeWire's view first."""
    seen: dict[str, str] = {}
    for source in sources:
        card = str(source_properties(source).get("alsa.id") or "")
        if card and card not in seen:
            seen[card] = source_label(source)
    for card, model in focusrite_cards().items():
        seen.setdefault(card, model)
    return list(seen.items())


def model_name(card: str) -> str:
    return focusrite_cards().get(card, "")


def parse_amixer_contents(text: str) -> dict[str, dict[str, Any]]:
    """Parse `amixer contents` into {control name: control}."""
    controls: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        header = re.match(r"^numid=(\d+),iface=\w+,name='(.*)'", line)
        if header:
            current = {"type": "", "items": [], "raw": None, "min": 0, "max": 0, "db": None, "numid": int(header.group(1))}
            controls[header.group(2)] = current
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped.startswith("; type="):
            fields = dict(part.split("=", 1) for part in stripped[2:].split(",") if "=" in part)
            current["type"] = fields.get("type", "")
            current["min"] = _int(fields.get("min"), 0)
            current["max"] = _int(fields.get("max"), 0)
        elif stripped.startswith("; Item #"):
            item = re.match(r"; Item #\d+ '(.*)'$", stripped)
            if item:
                current["items"].append(item.group(1))
        elif stripped.startswith(": values="):
            current["raw"] = stripped[len(": values="):].split(",")[0]
        elif stripped.startswith(("| dBminmax-", "| dBlinear-")):
            limits = re.findall(r"(-?\d+(?:\.\d+)?)dB", stripped)
            if len(limits) == 2:
                scale = "linear" if "dBlinear" in stripped else "minmax"
                current["db"] = (scale, float(limits[0]), float(limits[1]))
        elif stripped.startswith("| dBscale-"):
            limits = re.findall(r"(-?\d+(?:\.\d+)?)dB", stripped)
            if len(limits) == 2:
                low, step = float(limits[0]), float(limits[1])
                current["db"] = ("minmax", low, low + step * (current["max"] - current["min"]))
    return {name: _normalize(control) for name, control in controls.items()}


def parse_state_file(text: str) -> dict[str, dict[str, dict[str, Any]]]:
    """Parse an alsactl state file into {card id: {control name: control}}."""
    cards: dict[str, dict[str, dict[str, Any]]] = {}
    block: dict[str, dict[str, Any]] | None = None
    control: dict[str, Any] | None = None
    in_comment = False
    for line in text.splitlines():
        stripped = line.strip()
        state = re.match(r"^state\.(\S+)\s*\{$", stripped)
        if state:
            block = cards.setdefault(state.group(1), {})
            continue
        if block is None:
            continue
        if re.match(r"^control\.\d+\s*\{$", stripped):
            control = {
                "name": None, "type": "", "items": [], "raw": None, "min": 0, "max": 0, "db": None, "db_value": None,
            }
            continue
        if control is None:
            continue
        if stripped == "comment {":
            in_comment = True
            continue
        if stripped == "}":
            if in_comment:
                in_comment = False
            else:
                if control["name"] is not None:
                    block[control["name"]] = _normalize(control)
                control = None
            continue
        match = re.match(r"^(\S+)\s+(.*)$", stripped)
        if not match:
            continue
        key, value = match.group(1), _unquote(match.group(2))
        if in_comment:
            if key == "type":
                control["type"] = value
            elif key == "range":
                bounds = re.match(r"^(-?\d+)\s*-\s*(-?\d+)", value)
                if bounds:
                    control["min"], control["max"] = int(bounds.group(1)), int(bounds.group(2))
            elif key in ("dbmin", "dbmax"):
                _, low, high = control["db"] or ("minmax", 0.0, 0.0)
                hundredths = _int(value, 0) / 100
                control["db"] = ("minmax", hundredths, high) if key == "dbmin" else ("minmax", low, hundredths)
            elif re.match(r"^item\.\d+$", key):
                control["items"].append(value)
            elif key == "dbvalue.0":
                # alsactl already resolved the TLV, whatever its scale type.
                control["db_value"] = _int(value, 0) / 100
        elif key == "name":
            control["name"] = value
        elif key in ("value", "value.0"):
            control["raw"] = value
    return cards


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1]
    return value


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize(control: dict[str, Any]) -> dict[str, Any]:
    """Reduce a parsed control to {"value", "min", "max", "db"}."""
    raw = control.get("raw")
    items = control.get("items") or []
    value: Any = raw
    if control.get("type") == "ENUMERATED":
        # amixer reports an item index; alsactl reports the item label.
        index = _int(raw, -1)
        value = items[index] if items and 0 <= index < len(items) and str(raw).isdigit() else raw
    elif control.get("type") == "INTEGER":
        value = _int(raw, 0)
    elif control.get("type") == "BOOLEAN":
        value = str(raw).lower() in ("on", "true", "1")
    return {
        "value": value,
        "min": control.get("min", 0),
        "max": control.get("max", 0),
        "db": control.get("db"),
        "db_value": control.get("db_value"),
        "items": list(items),
        "numid": control.get("numid"),
    }


def read_controls(card: str) -> dict[str, dict[str, Any]]:
    try:
        return parse_amixer_contents(run(["amixer", "-c", card, "contents"]))
    except MonitorError:
        return {}


def control_level(controls: dict[str, dict[str, Any]], name: str) -> int | None:
    control = controls.get(name + " Playback Volume")
    return control["value"] if control and isinstance(control["value"], int) else None


# --- Hardware monitoring -----------------------------------------------------

def hardware_monitor(card: str, label: str, controls: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    left = control_level(controls, LEFT_CONTROL)
    right = control_level(controls, RIGHT_CONTROL)
    if left is None or right is None:
        return None
    return {"card": card, "label": label, "left": left, "right": right}


def find_hardware_monitor(sources: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    for card, label in candidate_cards(scarlett_sources() if sources is None else sources):
        monitor = hardware_monitor(card, label, read_controls(card))
        if monitor:
            return monitor
    return None


def set_raw_monitor_level(card: str, value: int) -> None:
    value = max(0, min(UNITY_LEVEL, value))
    run(["amixer", "-q", "-c", card, "sset", LEFT_CONTROL, str(value)])
    run(["amixer", "-q", "-c", card, "sset", RIGHT_CONTROL, str(value)])


# --- Routing -----------------------------------------------------------------

def parse_source(label: Any) -> tuple[str, int] | None:
    """Turn a routing item such as 'Mix E' or 'PCM 3' into (kind, index)."""
    match = SOURCE_ITEM.match(str(label or ""))
    if not match:
        return None
    index = match.group(2)
    number = ord(index) - ord("A") + 1 if index.isalpha() else int(index)
    return SOURCE_KINDS[match.group(1)], number


def _index_label(kind: str, index: int) -> str:
    return chr(ord("A") + index - 1) if kind == "mix" else str(index)


def source_text(kind: str, first: int, count: int = 1) -> str:
    name = SOURCE_NAMES.get(kind, kind)
    if count == 1:
        return f"{name} {_index_label(kind, first)}"
    return f"{name} {_index_label(kind, first)}–{_index_label(kind, first + count - 1)}"


def destination_text(kind: str, first: int, count: int, model: str) -> str:
    if kind == "out":
        named = OUTPUT_NAMES.get(model, {}).get((first, first + count - 1))
        if named:
            return named
    name = DESTINATION_NAMES[kind]
    return f"{name} {first}" if count == 1 else f"{name} {first}–{first + count - 1}"


def mix_gain_db(control: dict[str, Any]) -> float | None:
    if control.get("db_value") is not None:
        return control["db_value"]
    if not control["db"] or control["max"] <= control["min"]:
        return None
    scale, low, high = control["db"]
    span = control["max"] - control["min"]
    if scale == "linear":
        # Raw steps are amplitude, topping out at `high` dB.
        return 20 * math.log10((control["value"] - control["min"]) / span) + high
    return low + (control["value"] - control["min"]) * (high - low) / span


def routing_tables(controls: dict[str, dict[str, Any]]) -> dict[str, Any]:
    destinations: dict[str, dict[int, tuple[str, int] | None]] = {}
    names: dict[str, dict[int, str]] = {}
    mixer_inputs: dict[int, tuple[str, int] | None] = {}
    dsp_inputs: dict[int, tuple[str, int] | None] = {}
    mixes: dict[int, list[tuple[tuple[str, int], int | None]]] = {}
    for name, control in controls.items():
        mixer = MIXER_INPUT.match(name)
        if mixer:
            mixer_inputs[int(mixer.group(1))] = parse_source(control["value"])
            continue
        dsp = DSP_INPUT.match(name)
        if dsp:
            dsp_inputs[int(dsp.group(1))] = parse_source(control["value"])
            continue
        for pattern, kind in DESTINATIONS:
            match = pattern.match(name)
            if match:
                destinations.setdefault(kind, {})[int(match.group(1))] = parse_source(control["value"])
                names.setdefault(kind, {})[int(match.group(1))] = name
                break
    for name, control in controls.items():
        gain = MIX_GAIN.match(name)
        if not gain or not isinstance(control["value"], int) or control["value"] <= control["min"]:
            continue
        switch = controls.get(name.replace("Volume", "Switch"))
        if switch and switch["value"] is False:
            continue
        source = mixer_inputs.get(int(gain.group(2)))
        if source is None:
            continue
        db = mix_gain_db(control)
        mixes.setdefault(ord(gain.group(1)) - ord("A") + 1, []).append(
            (source, None if db is None else round(db))
        )
    return {"destinations": destinations, "names": names, "dsp": dsp_inputs, "mixes": mixes}


def _chain(source: tuple[str, int] | None, tables: dict[str, Any]) -> tuple:
    """Describe what feeds one destination channel, mixes expanded."""
    if source is None:
        return ("off",)
    if source[0] == "mix":
        return ("mix", source[1], tuple(sorted(tables["mixes"].get(source[1], []))))
    return ("src", source)


def _merge_sources(per_channel: list[list[tuple[tuple[str, int], int | None]]]) -> list[tuple] | None:
    """Merge the inputs of a run of mixes into (source, count, db) terms.

    Each input of the first mix must pair one-to-one with an input of every
    other mix: the same source (mono, in all of them) or the next channel
    along (stereo). Anything left over means the mixes are not a matched set.
    """
    first, remaining = per_channel[0], [list(items) for items in per_channel[1:]]
    if any(len(items) != len(first) for items in remaining):
        return None
    merged = []
    for (kind, index), db in first:
        shared = [((kind, index), db)] * len(remaining)
        stepped = [((kind, index + offset), db) for offset in range(1, len(remaining) + 1)]
        for wanted, count in ((shared, 1), (stepped, len(per_channel))):
            if all(item in items for item, items in zip(wanted, remaining)):
                for item, items in zip(wanted, remaining):
                    items.remove(item)
                merged.append(((kind, index), count, db))
                break
        else:
            return None
    return merged


def _describe_run(chains: list[tuple]) -> dict[str, Any] | None:
    """Collapse a run of destination channels into one row, if they line up."""
    count = len(chains)
    if all(chain == chains[0] for chain in chains):
        if chains[0][0] == "off":
            return {"via": None, "sources": [], "off": True}
        if chains[0][0] == "src":
            return {"via": None, "sources": [(chains[0][1], 1, None)]}
        return {"via": ("mix", chains[0][1], 1), "sources": [(s, 1, db) for s, db in chains[0][2]]}
    kinds = {chain[0] for chain in chains}
    if kinds == {"src"}:
        kind, index = chains[0][1]
        if all(chain[1] == (kind, index + offset) for offset, chain in enumerate(chains)):
            return {"via": None, "sources": [((kind, index), count, None)]}
        return None
    if kinds == {"mix"} and all(chain[1] == chains[0][1] + offset for offset, chain in enumerate(chains)):
        sources = _merge_sources([list(chain[2]) for chain in chains])
        if sources is not None:
            return {"via": ("mix", chains[0][1], count), "sources": sources}
    return None


def _fold_sources(sources: list[tuple]) -> list[tuple]:
    """Fold neighbouring terms (In 1, In 2, In 3 at one level) into ranges."""
    folded: list[list] = []
    for (kind, index), count, db in sorted(sources, key=lambda term: (term[0], term[1])):
        last = folded[-1] if folded else None
        if (
            last and kind != "dsp" and last[0] == kind and last[3] == db and last[4] == count
            and index == last[1] + last[2]
        ):
            last[2] += count
        else:
            folded.append([kind, index, count, db, count])
    return [((kind, index), span, db) for kind, index, span, db, _ in folded]


def _plural(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


def _numbers(first: int, count: int, kind: str = "") -> str:
    return _index_label(kind, first) if count == 1 else f"{_index_label(kind, first)}–{_index_label(kind, first + count - 1)}"


def source_hint(kind: str, first: int, count: int, dsp: bool = False) -> str:
    numbers = _numbers(first, count, kind)
    hints = {
        "in": f"{_plural(count, 'Input', 'Inputs')} {numbers} on the interface",
        "pc": f"Audio your computer plays on {_plural(count, 'channel', 'channels')} {numbers}",
        "spdif": f"S/PDIF digital {_plural(count, 'input', 'inputs')} {numbers}",
        "adat": f"ADAT optical {_plural(count, 'input', 'inputs')} {numbers}",
        "dsp": f"DSP {_plural(count, 'channel', 'channels')} {numbers}",
        "mix": f"Internal {_plural(count, 'mix', 'mixes')} {numbers}: blends its sources, each at its own level",
    }
    hint = hints.get(kind, "")
    return hint + ", after the interface's input processing (DSP)" if dsp else hint


def destination_hint(kind: str, first: int, count: int, label: str) -> str:
    numbers = _numbers(first, count)
    if label == "Phones":
        return "Headphone output"
    if label.startswith("Line"):
        return f"Line {_plural(count, 'output', 'outputs')} {numbers}, usually your monitor speakers"
    hints = {
        "out": f"Analogue {_plural(count, 'output', 'outputs')} {numbers}",
        "spdif": f"S/PDIF digital {_plural(count, 'output', 'outputs')} {numbers}",
        "adat": f"ADAT optical {_plural(count, 'output', 'outputs')} {numbers}",
        "rec": f"What applications record on {_plural(count, 'channel', 'channels')} {numbers}",
    }
    return hints[kind]


def _source_chip(source: tuple[str, int], count: int, db: int | None, tables: dict[str, Any]) -> dict[str, Any]:
    kind, index = source
    label = source_text(kind, index, count)
    hint = source_hint(kind, index, count)
    if kind == "dsp":
        # DSP channels are processed inputs; name them after what feeds them.
        feeds = [tables["dsp"].get(index + offset) for offset in range(count)]
        if feeds[0] and all(feed == (feeds[0][0], feeds[0][1] + offset) for offset, feed in enumerate(feeds)):
            label = source_text(feeds[0][0], feeds[0][1], count) + " (DSP)"
            kind = feeds[0][0]
            hint = source_hint(kind, feeds[0][1], count, dsp=True)
    if db not in (None, 0):
        hint += f", mixed in at {'+' if db > 0 else '−'}{abs(db)} dB"
    return {"label": label, "kind": kind, "db": db, "hint": hint}


def item_label(kind: str, index: int) -> str:
    """The ALSA enum item for a source, e.g. ('pc', 3) -> 'PCM 3'."""
    return f"{ITEM_NAMES[kind]} {_index_label(kind, index)}"


def _choice_label(kind: str, start: int, span: int, count: int, tables: dict[str, Any]) -> str:
    label = source_text(kind, start, span) if kind == "mix" else _source_chip((kind, start), span, None, tables)["label"]
    return label + " (mono)" if span == 1 and count > 1 else label


def _choice(kind: str, start: int, span: int, count: int, tables: dict[str, Any]) -> dict[str, Any]:
    # A DSP choice takes the icon of the input it processes, like its chip.
    icon = _source_chip((kind, start), span, None, tables)["kind"] if kind != "mix" else "mix"
    return {
        "key": f"{kind}:{start}:{span}",
        "label": _choice_label(kind, start, span, count, tables),
        "kind": icon,
        "group": CHOICE_GROUPS[kind],
    }


def route_choices(items: list[str], count: int, current: str, tables: dict[str, Any]) -> list[dict[str, Any]]:
    """Sources a destination run can switch to: aligned groups of its width."""
    available: dict[str, set[int]] = {}
    for item in items:
        source = parse_source(item)
        if source:
            available.setdefault(source[0], set()).add(source[1])
    choices = []
    for kind in CHOICE_ORDER:
        indices = available.get(kind, set())
        for start in range(1, max(indices, default=0) + 1, count):
            if all(start + offset in indices for offset in range(count)):
                choices.append(_choice(kind, start, count, count, tables))
    choices.append({"key": "off", "label": "Off", "kind": "", "group": "Mixes" if "mix" in available else ""})
    if current not in {choice["key"] for choice in choices}:
        # A mono source shared across a pair, or an unaligned range.
        kind, start, span = current.split(":")
        choices.insert(0, _choice(kind, int(start), int(span), count, tables))
    for choice in choices:
        choice["current"] = choice["key"] == current
    return choices


def _current_choice(best: dict[str, Any], count: int) -> str:
    if best.get("off"):
        return "off"
    if best["via"]:
        _, mix, span = best["via"]
        return f"mix:{mix}:{span}"
    (kind, index), span, _ = best["sources"][0]
    return f"{kind}:{index}:{span}"


def routing_rows(controls: dict[str, dict[str, Any]], model: str = "") -> list[dict[str, Any]]:
    tables = routing_tables(controls)
    rows: list[dict[str, Any]] = []
    for kind in ("out", "spdif", "adat", "rec"):
        channels = sorted(tables["destinations"].get(kind, {}).items())
        position = 0
        while position < len(channels):
            # Grow the longest run of consecutive channels that still collapses
            # into one row: a stereo pair, a mono source on both sides, or a
            # bank of inputs recorded straight to the computer. Physical outputs
            # and unused channels stop at their odd/even pair so front-panel
            # names stay visible and Off channels can be picked a pair at a time.
            first = channels[position][0]
            limit = len(channels) - position
            if kind != "rec" or channels[position][1] is None:
                limit = min(limit, 2 if first % 2 else 1)
            best_length, best = 1, None
            for length in range(1, limit + 1):
                window = channels[position:position + length]
                if any(window[i][0] != window[0][0] + i for i in range(length)):
                    break
                described = _describe_run([_chain(source, tables) for _, source in window])
                if described is None:
                    if length > 1:
                        break
                    continue
                best_length, best = length, described
            if best is None:
                best = {"via": None, "sources": [(channels[position][1], 1, None)]}
            via = best["via"]
            destination = destination_text(kind, first, best_length, model)
            current = _current_choice(best, best_length)
            items = controls[tables["names"][kind][first]].get("items") or []
            rows.append({
                "key": f"{kind}:{first}:{best_length}",
                "section": "record" if kind == "rec" else "hear",
                "kind": "phones" if destination == "Phones" else kind,
                "destination": destination,
                "destination_hint": destination_hint(kind, first, best_length, destination),
                "off": bool(best.get("off")),
                "via": source_text(*via) if via else "",
                "via_hint": source_hint("mix", via[1], via[2]) if via else "",
                "sources": [
                    _source_chip(source, count, db, tables) for source, count, db in _fold_sources(best["sources"])
                ],
                "same_as": "",
                "current": current,
                "choices": route_choices(items, best_length, current, tables) if items else [],
            })
            position += best_length
    # A recording channel fed by the same mix as an output (Rec 5–6 and Phones
    # on a 4th Gen) is shown once, then referred to.
    seen: dict[str, str] = {}
    for row in rows:
        if not row["via"]:
            continue
        signature = json.dumps([row["via"], row["sources"]], sort_keys=True)
        if signature in seen:
            row["same_as"] = seen[signature]
        else:
            seen[signature] = row["destination"]
    return rows


def set_route(row_key: str, choice_key: str) -> dict[str, Any]:
    """Point a destination run at a new source; nothing is written unless
    every channel accepts it."""
    row, choice = ROW_KEY.match(str(row_key)), CHOICE_KEY.match(str(choice_key))
    if not row or not choice:
        raise MonitorError("Unknown route")
    kind, first, count = row.group(1), int(row.group(2)), int(row.group(3))
    card = require_card()
    controls = read_controls(card)
    tables = routing_tables(controls)
    names = tables["names"].get(kind, {})
    targets = [names.get(first + offset) for offset in range(count)] if 1 <= count <= 64 else []
    if not targets or not all(targets):
        raise MonitorError("That output is not available on this interface")
    if choice_key == "off":
        labels, chosen = ["Off"] * count, "Off"
    else:
        source, start, span = choice.group(1), int(choice.group(2)), int(choice.group(3))
        if span not in (1, count):
            raise MonitorError("Unknown route")
        labels = [item_label(source, start + (offset if span == count else 0)) for offset in range(count)]
        chosen = _choice_label(source, start, span, count, tables)
    commands = []
    for name, label in zip(targets, labels):
        control = controls[name]
        if label not in control["items"]:
            raise MonitorError(f"{label} cannot be routed there on this interface")
        target = f"numid={control['numid']}" if control.get("numid") else f"name={name}"
        commands.append(["amixer", "-q", "-c", card, "cset", target, str(control["items"].index(label))])
    for command in commands:
        run(command)
    result = status()
    destination = destination_text(kind, first, count, model_name(card))
    result["notice"] = f"{destination} is now off" if choice_key == "off" else f"{destination} now plays {chosen}"
    return result


def routing_signature(controls: dict[str, dict[str, Any]]) -> dict[str, str]:
    """The routing selections a preset is compared on, gains excluded."""
    signature = {}
    for name, control in controls.items():
        if MIXER_INPUT.match(name) or DSP_INPUT.match(name) or any(p.match(name) for p, _ in DESTINATIONS):
            signature[name] = str(control["value"])
    return signature


# --- Presets -----------------------------------------------------------------

def preset_path(name: str) -> Path:
    name = str(name).strip()
    if not PRESET_NAME.match(name) or name.endswith("."):
        raise MonitorError("Preset names may use letters, numbers, spaces, dots, dashes, and underscores")
    return presets_dir() / (name + PRESET_SUFFIX)


def preset_block(path: Path, card: str) -> dict[str, dict[str, Any]] | None:
    """Controls stored for this card, or the file's only card when ids differ."""
    try:
        cards = parse_state_file(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None
    if card in cards:
        return cards[card]
    return next(iter(cards.values())) if len(cards) == 1 else None


def list_presets(card: str, controls: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    current = routing_signature(controls)
    presets = []
    try:
        paths = sorted(presets_dir().glob("*" + PRESET_SUFFIX), key=lambda item: item.stem.lower())
    except OSError:
        return []
    for path in paths:
        if not path.is_file() or not PRESET_NAME.match(path.stem):
            continue
        block = preset_block(path, card)
        stored = routing_signature(block) if block else {}
        shared = [name for name in stored if name in current]
        presets.append({
            "name": path.stem,
            "active": bool(shared) and all(stored[name] == current[name] for name in shared),
            "compatible": bool(shared),
        })
    return presets


def interface_card(sources: list[dict[str, Any]]) -> tuple[str, str] | None:
    """The card routing is read from: the first one exposing routing controls."""
    candidates = candidate_cards(sources)
    for card, label in candidates:
        if routing_signature(read_controls(card)):
            return card, label
    return candidates[0] if candidates else None


def require_card() -> str:
    found = interface_card(scarlett_sources())
    if not found:
        raise MonitorError("No Scarlett interface is connected")
    return found[0]


def save_preset(name: str) -> dict[str, Any]:
    card = require_card()
    path = preset_path(name)
    if path.exists():
        raise MonitorError(f"A preset named '{path.stem}' already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    run(["alsactl", "-f", str(path), "store", card])
    return dict(status(), notice=f"Saved {path.stem}")


def delete_preset(name: str) -> dict[str, Any]:
    path = preset_path(name)
    if not path.is_file():
        raise MonitorError(f"Preset '{path.stem}' was not found")
    path.unlink()
    return dict(status(), notice=f"Deleted {path.stem}")


def apply_preset(name: str) -> dict[str, Any]:
    card = require_card()
    path = preset_path(name)
    if not path.is_file():
        raise MonitorError(f"Preset '{path.stem}' was not found")
    text = path.read_text(encoding="utf-8")
    cards = parse_state_file(text)
    block = cards.get(card) or (next(iter(cards.values())) if len(cards) == 1 else None)
    current = routing_signature(read_controls(card))
    if block is None or not set(routing_signature(block)) & set(current):
        raise MonitorError(f"Preset '{path.stem}' does not contain a configuration for this interface")
    if card not in cards:
        # Card ids differ between machines (Gen, USB, USB_1...); retarget the
        # preset's only block at the connected interface.
        text = re.sub(r"(?m)^state\.\S+(\s*\{)", lambda match: f"state.{card}{match.group(1)}", text, count=1)
    runtime = os.environ.get("XDG_RUNTIME_DIR") or None
    with tempfile.NamedTemporaryFile("w", suffix=PRESET_SUFFIX, dir=runtime, delete=False, encoding="utf-8") as handle:
        handle.write(text)
        temporary = handle.name
    try:
        # -I: if the restore fails, never fall back to re-initialising the
        # card, which would reset every level on the interface.
        run(["alsactl", "-I", "-f", temporary, "restore", card])
    finally:
        os.unlink(temporary)
    return dict(status(), notice=f"Applied {path.stem}")


# --- Commands ----------------------------------------------------------------

def status() -> dict[str, Any]:
    # One source listing and one control read per card feed every lookup; this
    # runs on every poll.
    sources = scarlett_sources()
    mic = find_scarlett_mic(sources)
    monitor = None
    routing_card: tuple[str, str, dict[str, dict[str, Any]]] | None = None
    for card, label in candidate_cards(sources):
        controls = read_controls(card)
        monitor = monitor or hardware_monitor(card, label, controls)
        if routing_card is None and routing_signature(controls):
            routing_card = (card, label, controls)
    level = max(int(monitor["left"]), int(monitor["right"])) if monitor else 0
    rows = routing_rows(routing_card[2], model_name(routing_card[0])) if routing_card else []
    presets = list_presets(routing_card[0], routing_card[2]) if routing_card else []
    return {
        "ok": True,
        "mic_available": mic is not None,
        "mic_muted": bool(mic and mic["muted"]),
        "mic_device": str(mic["label"] if mic else "Scarlett microphone"),
        "monitor_available": monitor is not None,
        "monitor_enabled": bool(monitor and level > 0),
        "monitor_volume": max(0, min(100, round(level / UNITY_LEVEL * 100))),
        "monitor_device": str(monitor["label"] if monitor else "Scarlett interface"),
        "routing_available": routing_card is not None,
        "routing": rows,
        "presets": presets,
        "presets_dir": str(presets_dir()),
        "routing_view": load_config()["routing_view"],
        "mixer_app_installed": shutil.which(MIXER_APP) is not None,
        "mixer_app_installable": shutil.which("omarchy-pkg-add") is not None,
        "message": "" if mic else "Connect a Scarlett interface to control its microphone.",
    }


def toggle_mic() -> dict[str, Any]:
    mic = find_scarlett_mic()
    if not mic:
        raise MonitorError("No Scarlett capture source is available")
    run(["pactl", "set-source-mute", str(mic["name"]), "toggle"])
    return status()


def toggle_monitor(config: dict[str, Any]) -> dict[str, Any]:
    monitor = find_hardware_monitor()
    if not monitor:
        raise MonitorError("Compatible Scarlett hardware-monitor controls are unavailable")
    current = max(int(monitor["left"]), int(monitor["right"]))
    if current > 0:
        config["last_monitor_volume"] = max(1, min(100, round(current / UNITY_LEVEL * 100)))
        raw = 0
    else:
        raw = round(int(config["last_monitor_volume"]) / 100 * UNITY_LEVEL)
    save_config(config)
    set_raw_monitor_level(str(monitor["card"]), raw)
    return status()


def set_monitor_volume(config: dict[str, Any], percent: int) -> dict[str, Any]:
    monitor = find_hardware_monitor()
    if not monitor:
        raise MonitorError("Compatible Scarlett hardware-monitor controls are unavailable")
    percent = max(0, min(100, percent))
    if percent > 0:
        config["last_monitor_volume"] = percent
        save_config(config)
    set_raw_monitor_level(str(monitor["card"]), round(percent / 100 * UNITY_LEVEL))
    return status()


def dispatch(arguments: list[str]) -> dict[str, Any]:
    command = arguments[0] if arguments else "status"
    config = load_config()
    if command == "status":
        return status()
    if command == "mic-toggle":
        return toggle_mic()
    if command == "monitor-toggle":
        return toggle_monitor(config)
    if command == "monitor-volume" and len(arguments) == 2:
        return set_monitor_volume(config, int(arguments[1]))
    if command == "preset-apply" and len(arguments) == 2:
        return apply_preset(arguments[1])
    if command == "preset-save" and len(arguments) == 2:
        return save_preset(arguments[1])
    if command == "preset-delete" and len(arguments) == 2:
        return delete_preset(arguments[1])
    if command == "route-set" and len(arguments) == 3:
        return set_route(arguments[1], arguments[2])
    if command == "routing-view" and len(arguments) == 2 and arguments[1] in ROUTING_VIEWS:
        config["routing_view"] = arguments[1]
        save_config(config)
        return status()
    raise MonitorError(
        "Usage: scarlett_monitor.py [status|mic-toggle|monitor-toggle|monitor-volume PERCENT"
        "|preset-apply NAME|preset-save NAME|preset-delete NAME|route-set ROW CHOICE|routing-view compact|all]"
    )


def main() -> int:
    try:
        result = dispatch(sys.argv[1:])
    except (MonitorError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
