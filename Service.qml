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
  property var pendingCommand: null

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

  function run(args) {
    var command = ["python3", helperPath].concat(args)
    if (helper.running) {
      pendingCommand = command
      return
    }
    helper.command = command
    helper.running = true
  }

  function refresh() { run(["status"]) }
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
      if (root.pendingCommand) {
        var next = root.pendingCommand
        root.pendingCommand = null
        helper.command = next
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

  IpcHandler {
    target: "scarlett-mic-control"
    function refresh(): void { root.refresh() }
    function status(): string {
      return JSON.stringify({
        micAvailable: root.micAvailable, micMuted: root.micMuted, micDevice: root.micDevice,
        monitorAvailable: root.monitorAvailable, monitorEnabled: root.monitorEnabled,
        monitorVolume: root.monitorVolume, monitorDevice: root.monitorDevice,
        message: root.message, error: root.lastError
      })
    }
    function toggleMic(): void { root.toggleMic() }
    function toggleMonitor(): void { root.toggleMonitor() }
    function monitorVolume(percent: int): void { root.setMonitorVolume(percent) }
  }
}
