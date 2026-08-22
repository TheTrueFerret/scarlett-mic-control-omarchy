#!/usr/bin/env python3
"""Control Scarlett capture mute and compatible hardware monitoring."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


UNITY_LEVEL = 160
LEFT_CONTROL = "Mix E Input 01"
RIGHT_CONTROL = "Mix F Input 01"


class MonitorError(RuntimeError):
    pass


def config_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "omarchy" / "scarlett-mic-control.json"


def load_config() -> dict[str, Any]:
    try:
        value = json.loads(config_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": 1, "last_monitor_volume": 75}
    except (OSError, json.JSONDecodeError) as exc:
        raise MonitorError(f"Could not read monitor settings: {exc}") from exc
    if not isinstance(value, dict):
        return {"version": 1, "last_monitor_volume": 75}
    try:
        volume = int(value.get("last_monitor_volume", 75))
    except (TypeError, ValueError):
        volume = 75
    return {"version": 1, "last_monitor_volume": max(1, min(100, volume))}


def save_config(config: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def run(command: list[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=6, check=False)
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
    sources = pactl_json("list", "sources")
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


def find_scarlett_mic() -> dict[str, Any] | None:
    sources = scarlett_sources()
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


def mixer_value(card: str, control: str) -> int | None:
    try:
        output = run(["amixer", "-c", card, "sget", control])
    except MonitorError:
        return None
    match = re.search(r"(?:Mono|Front Left): Playback\s+(\d+)", output)
    return int(match.group(1)) if match else None


def find_hardware_monitor() -> dict[str, Any] | None:
    for source in scarlett_sources():
        card = str(source_properties(source).get("alsa.id") or "")
        if not card:
            continue
        left = mixer_value(card, LEFT_CONTROL)
        right = mixer_value(card, RIGHT_CONTROL)
        if left is None or right is None:
            continue
        return {"card": card, "label": source_label(source), "left": left, "right": right}
    return None


def set_raw_monitor_level(card: str, value: int) -> None:
    value = max(0, min(UNITY_LEVEL, value))
    run(["amixer", "-q", "-c", card, "sset", LEFT_CONTROL, str(value)])
    run(["amixer", "-q", "-c", card, "sset", RIGHT_CONTROL, str(value)])


def status() -> dict[str, Any]:
    mic = find_scarlett_mic()
    monitor = find_hardware_monitor()
    level = max(int(monitor["left"]), int(monitor["right"])) if monitor else 0
    return {
        "ok": True,
        "mic_available": mic is not None,
        "mic_muted": bool(mic and mic["muted"]),
        "mic_device": str(mic["label"] if mic else "Scarlett microphone"),
        "monitor_available": monitor is not None,
        "monitor_enabled": bool(monitor and level > 0),
        "monitor_volume": max(0, min(100, round(level / UNITY_LEVEL * 100))),
        "monitor_device": str(monitor["label"] if monitor else "Scarlett interface"),
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
    raise MonitorError(
        "Usage: scarlett_monitor.py [status|mic-toggle|monitor-toggle|monitor-volume PERCENT]"
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
