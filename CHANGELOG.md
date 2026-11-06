# Changelog

All notable changes to this project will be documented here.

## 1.1.0 — 2026-11-06

- Show the interface's current routing in the panel: what each output and
  computer recording channel plays, through which mix, at what level.
- Add routing presets: save the current routing, or a configuration saved from
  ALSA Scarlett Control Panel, and switch between them from the bar.
- Add an Open mixer button for ALSA Scarlett Control Panel
  (`alsa-scarlett-gui`), with a one-click install when it is missing.
- Find Focusrite interfaces through ALSA when PipeWire does not report them.
- Fix the panel IPC route, command queueing, and recovery from a damaged
  preferences file.

## 1.0.0 — 2026-08-23

- Add Scarlett capture mute for applications and calls.
- Add independent zero-latency headphone-monitor toggle and volume controls for
  compatible Scarlett mixer interfaces.
- Add themed Omarchy bar widget, keyboard controls, and shell IPC.
- Add automatic Scarlett discovery through PipeWire metadata.
