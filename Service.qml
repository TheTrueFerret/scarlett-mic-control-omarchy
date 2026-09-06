import QtQuick
import Quickshell
import Quickshell.Io

Item {
  id: root

  property var shell: null
  property bool micAvailable: false
  property bool micMuted: false
  property string micDevice: "Scarlett microphone"
  property bool monitorAvailable: false
  property bool monitorEnabled: false
  property int monitorVolume: 0
  property string monitorDevice: "Scarlett interface"
  property string message: ""
  property string lastError: ""
  property var queue: []

  readonly property bool busy: helper.running
  readonly property string helperPath: decodeURIComponent(
    String(Qt.resolvedUrl("scarlett_monitor.py")).replace(/^file:\/\//, "")
  )

  function consume(raw) {
    var text = String(raw || "").trim()
    if (!text) return
    try {
      var data = JSON.parse(text)
      if (!data.ok) {
        lastError = String(data.error || "Microphone control failed")
        return
      }
      micAvailable = data.mic_available === true
      micMuted = data.mic_muted === true
      micDevice = String(data.mic_device || "Scarlett microphone")
      monitorAvailable = data.monitor_available === true
      monitorEnabled = data.monitor_enabled === true
      monitorVolume = Math.max(0, Math.min(100, Number(data.monitor_volume || 0)))
      monitorDevice = String(data.monitor_device || "Scarlett interface")
      message = String(data.message || "")
      lastError = ""
    } catch (error) {
      lastError = "Scarlett control returned invalid data"
    }
  }

  function statusJson() {
    return JSON.stringify({
      micAvailable: micAvailable, micMuted: micMuted, micDevice: micDevice,
      monitorAvailable: monitorAvailable, monitorEnabled: monitorEnabled,
      monitorVolume: monitorVolume, monitorDevice: monitorDevice,
      message: message, error: lastError
    })
  }

  function run(args) {
    if (!helper.running) {
      helper.command = ["python3", helperPath].concat(args)
      helper.running = true
      return
    }
    // Only polls and volume drags collapse into the queued command; a discrete
    // toggle must never be dropped because another command was still running.
    var pending = queue.slice()
    var last = pending.length ? pending[pending.length - 1] : null
    if (last && last[0] === args[0] && (args[0] === "status" || args[0] === "monitor-volume"))
      pending[pending.length - 1] = args
    else
      pending.push(args)
    queue = pending
  }

  function refresh() {
    // Every command answers with fresh status, so a poll behind a queued
    // command is redundant.
    if (helper.running && queue.length > 0) return
    run(["status"])
  }
  function toggleMic() { run(["mic-toggle"]) }
  function toggleMonitor() { run(["monitor-toggle"]) }
  function setMonitorVolume(percent) { run(["monitor-volume", String(Math.round(percent))]) }

  Process {
    id: helper
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.consume(text)
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var detail = String(text || "").trim()
        if (detail) root.lastError = detail
      }
    }
    onExited: function(exitCode) {
      if (exitCode !== 0 && !root.lastError) root.lastError = "Microphone command failed"
      if (root.queue.length > 0) {
        var pending = root.queue.slice()
        var next = pending.shift()
        root.queue = pending
        helper.command = ["python3", root.helperPath].concat(next)
        helper.running = true
      }
    }
  }

  Timer {
    interval: 3000
    repeat: true
    running: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  Component.onCompleted: refresh()
}
