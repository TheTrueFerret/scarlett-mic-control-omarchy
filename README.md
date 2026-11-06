# Scarlett Mic Control for Omarchy

A small, theme-aware Omarchy bar widget for a Focusrite Scarlett interface:

- **Microphone** controls what Discord, OBS, games, recordings, and other people
  receive.
- **Hear myself** independently controls compatible Scarlett zero-latency
  headphone monitoring.
- **Routing** shows at a glance what each output and each computer recording
  channel is fed by, and through which internal mix.
- **Presets** switch the interface between saved routings, and **Open mixer**
  jumps to [ALSA Scarlett Control Panel](https://github.com/geoffreybennett/alsa-scarlett-gui)
  for full editing.

Normal speakers, headphones, Bluetooth devices, and application routing remain
under Omarchy's built-in audio widget.

![Scarlett Mic Control panel in the Omarchy bar](assets/scarlett-mic-control.png)

## Install

Install the plugin and its mixer-app dependency, ALSA Scarlett Control Panel:

```bash
omarchy pkg add alsa-scarlett-gui
omarchy plugin add https://github.com/TheTrueFerret/scarlett-mic-control-omarchy.git --enable
```

`alsa-scarlett-gui` is in the Arch `extra` repository. If it is missing, the
panel shows an **Install mixer** button that runs the same `omarchy pkg add`
in a terminal, where you confirm it; the plugin never installs packages
silently. Mute, monitoring, the routing view, and presets work without it; only
**Open mixer** needs it.

The widget is placed on the right side of the bar by default. If it does not
appear immediately, restart the shell:

```bash
omarchy restart shell
```

## Controls

| Action | Result |
| --- | --- |
| Left-click the bar icon | Open the control panel |
| Right-click the bar icon | Mute or unmute the Scarlett microphone for applications |
| Middle-click the bar icon | Toggle compatible hardware monitoring |
| Scroll over the bar icon | Adjust hardware-monitor volume |
| `M` in the panel | Toggle microphone capture mute |
| `H` in the panel | Toggle headphone monitoring |
| `O` in the panel | Open ALSA Scarlett Control Panel |
| `S` in the panel | Save the current routing as a preset |
| `1`–`9` in the panel | Apply that preset |

The panel uses separate switches so muting yourself for a call never silently
changes what you hear in the headphones, and disabling monitoring never mutes
the recording source.

## Routing view

The panel reads the interface's routing straight from its ALSA mixer controls
and draws each route as a chain, for example:

```text
PC 1–2 → Mix A–B → Line 1–2        computer playback to the monitors
In 1 (DSP) −48 dB, PC 1–2 → Mix E–F → Phones
In 1–2 (DSP) → Rec 1–2             what applications record
```

- **In** is a hardware input, **PC** is computer playback, **Rec** is a channel
  the computer records, **Mix A–F** are the interface's internal mixes, and
  **(DSP)** marks an input that passes through the interface's processing.
- Stereo pairs and banks of channels are folded into one row; outputs and
  recording channels set to Off are hidden.
- Levels are shown only when a mix input is not at 0 dB.

The view refreshes every few seconds, so changes made in ALSA Scarlett Control
Panel appear on their own. Front-panel names (Line, Phones) are shown for the
Scarlett 4i4 4th Gen; other models use generic `Out` numbers.

## Presets

A preset is a standard `alsactl` state file, the same format ALSA Scarlett
Control Panel uses for **File › Save Configuration**. Presets live in:

```text
~/.config/omarchy/scarlett-mic-control/presets/
```

- **Save current** stores the interface's whole current state (routing, mixes,
  and levels) under a name you type. Existing presets are never overwritten.
- Configurations saved from the mixer app into that folder appear
  automatically.
- Clicking a preset restores it with `alsactl -I`, so a failed restore never
  falls back to resetting the interface to defaults.
- The preset whose routing matches the interface is highlighted. Levels are not
  compared, so moving the monitor slider keeps it highlighted.
- A preset saved on another computer works even though ALSA may name the card
  differently there (`Gen`, `USB`, `USB_1`, …): a preset with a single
  interface is applied to the connected one.

## Scripting

Every control is reachable over the shell IPC route named after the plugin id,
so it can be bound to a hotkey in `~/.config/hypr/bindings.lua`:

```bash
omarchy-shell io.github.thetrueferret.scarlett-mic-control toggleMic
omarchy-shell io.github.thetrueferret.scarlett-mic-control toggleMonitor
omarchy-shell io.github.thetrueferret.scarlett-mic-control monitorVolume 60
omarchy-shell io.github.thetrueferret.scarlett-mic-control status
omarchy-shell io.github.thetrueferret.scarlett-mic-control toggle
omarchy-shell io.github.thetrueferret.scarlett-mic-control openMixer
omarchy-shell io.github.thetrueferret.scarlett-mic-control applyPreset Streaming
omarchy-shell io.github.thetrueferret.scarlett-mic-control savePreset "Late night"
```

`toggle`, `open`, and `close` control the panel; `status` returns JSON.

## Compatibility

### Microphone mute

Capture mute is designed to work with **any Scarlett interface exposed as an
audio input by PipeWire**. The plugin discovers connected devices from their
Scarlett metadata and prefers the system's default Scarlett input when several
are connected.

### Hardware monitoring

Zero-latency monitoring varies substantially between Scarlett generations and
models. The current adapter is tested on the **Scarlett 4i4 4th Gen** and is
enabled only when ALSA exposes both of these mixer controls:

```text
Mix E Input 01
Mix F Input 01
```

The monitor percentage is scaled against unity gain, so 100% is 0 dB rather
than the interface's maximum boost. `alsamixer` reports the same level as a
percentage of the full control range and therefore shows a lower number.

### Routing view and presets

The routing view understands the controls exposed by the Linux `scarlett2`
driver and the user-space FCP driver, and is tested against the demo
configurations shipped with ALSA Scarlett Control Panel for:

- Scarlett 2nd Gen 6i6, 18i8, 18i20
- Scarlett 3rd Gen 4i4, 8i6, 18i8, 18i20
- Scarlett 4th Gen Solo, 2i2, 4i4, 16i16, 18i16, 18i20
- Clarett+ 2Pre, 4Pre, 8Pre, and Vocaster One and Two

The 3rd Gen Solo and 2i2 have no software routing, and 1st Gen interfaces use
an older driver with a different control layout, so the panel says routing is
not available for them. Mute and **Open mixer** still work. Interfaces are found
through PipeWire, or directly through ALSA by Focusrite's USB vendor id when
PipeWire does not list them.

### Unsupported monitoring layouts

On another Scarlett model, microphone mute can still work even if **Hear
myself** is shown as unavailable. The plugin deliberately avoids guessing at
unknown hardware routes. Use the interface's physical Direct Monitor control or
[ALSA Scarlett Control Panel](https://github.com/geoffreybennett/alsa-scarlett-gui)
for unsupported monitoring layouts.

## Requirements

- Omarchy with Quickshell plugin support
- PipeWire with its PulseAudio-compatible server (`pactl`)
- ALSA utilities (`amixer`, `alsactl`) for monitoring, routing, and presets
- [ALSA Scarlett Control Panel](https://github.com/geoffreybennett/alsa-scarlett-gui)
  (`alsa-scarlett-gui`) for **Open mixer**
- Python 3
- A Linux driver and firmware combination that exposes the controls supported
  by your Scarlett model

On Omarchy, `pactl`, `amixer`, `alsactl`, and Python are normally already
available; install the mixer app with `omarchy pkg add alsa-scarlett-gui`.

## Updating and removing

```bash
omarchy plugin update io.github.thetrueferret.scarlett-mic-control
omarchy plugin remove io.github.thetrueferret.scarlett-mic-control
```

The plugin writes only its remembered monitor level and the presets you save:

```text
~/.config/omarchy/scarlett-mic-control.json
~/.config/omarchy/scarlett-mic-control/presets/
```

Removing the plugin does not alter normal Omarchy audio settings, the
interface's current routing, or delete these files. Remove `alsa-scarlett-gui`
separately with `omarchy pkg drop alsa-scarlett-gui` if nothing else needs it.

## Troubleshooting

Check what the backend detects:

```bash
python3 ~/.config/omarchy/plugins/io.github.thetrueferret.scarlett-mic-control/scarlett_monitor.py status | jq
```

Confirm that PipeWire sees the interface:

```bash
pactl list short sources
```

Check whether the compatible monitoring controls exist, replacing `Gen` with
the ALSA card id shown on your system:

```bash
amixer -c Gen scontrols | grep 'Mix [EF] Input 01'
```

If **Routing** says it is not available, check whether the driver exposes
routing controls (again replacing `Gen` with your card id):

```bash
amixer -c Gen controls | grep -E "(Playback|Capture) Enum"
```

Lines such as `Analogue Output 01 Playback Enum` or `PCM 01 Capture Enum` mean
routing is exposed; please open an issue with that output if the panel still
shows nothing.

After updating plugin code, use `omarchy restart shell` if the old component is
still cached.

## Development

Validate the plugin using the same manifest checks as the Omarchy installer:

```bash
omarchy plugin validate .
python3 -m unittest discover -s tests -v
python3 -m py_compile scarlett_monitor.py
```

Omarchy plugins run as unsandboxed user code. This plugin executes fixed local
`pactl`, `amixer`, and `alsactl` commands, reads `/proc/asound` to find the
interface, and launches `alsa-scarlett-gui` when asked. Installing the mixer
app runs `omarchy pkg add alsa-scarlett-gui` in a visible terminal only after
you click **Install mixer**. It performs no network requests of its own and
reads no credentials.

See Omarchy's [shell plugin documentation](https://github.com/basecamp/omarchy/blob/quattro/manual/32-shell-plugins.md)
for the plugin lifecycle and manifest format.

## License

[MIT](LICENSE)
