# Changelog

All notable changes to this project will be documented here.

## 1.1.0 — 2026-11-06

- Show the interface's current routing in the panel: one row per output and
  computer recording channel saying what it plays, through which mix, and at
  what level, styled like Omarchy's audio panel, with a compact view of the
  outputs in use.
- Switch what an output or recording channel plays from the panel, by mouse or
  keyboard, among the sources the driver accepts for it.
- Add routing presets: save the current routing, or a configuration saved from
  ALSA Scarlett Control Panel, and switch between them from the bar. Presets
  can be cycled with `N` or the `nextPreset` IPC call, deleted after
  confirming, and the panel says when the current routing is not saved.
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
