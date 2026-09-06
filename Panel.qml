import QtQuick
import QtQuick.Controls
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "io.github.thetrueferret.scarlett-mic-control"
  ipcTarget: "io.github.thetrueferret.scarlett-mic-control"
  manageIpc: false

  readonly property var service: bar && bar.shell
    ? bar.shell.serviceFor("io.github.thetrueferret.scarlett-mic-control") : null
  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  property bool cursorActive: false
  property int focusRow: 0

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function adjustMonitorVolume(delta) {
    if (!service || !service.monitorAvailable || service.busy) return
    service.setMonitorVolume(Math.max(0, Math.min(100, service.monitorVolume + delta)))
  }

  function activateCursor() {
    if (!service || service.busy) return
    if (focusRow === 0 && service.micAvailable) service.toggleMic()
    else if (focusRow === 1 && service.monitorAvailable) service.toggleMonitor()
  }

  onOpenedChanged: if (opened) {
    cursorActive = false
    focusRow = 0
    if (service) service.refresh()
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  IpcHandler {
    target: root.ipcTarget

    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
    function refresh(): void { if (root.service) root.service.refresh() }
    function status(): string { return root.service ? root.service.statusJson() : "" }
    function toggleMic(): void { if (root.service) root.service.toggleMic() }
    function toggleMonitor(): void { if (root.service) root.service.toggleMonitor() }
    function monitorVolume(percent: int): void { if (root.service) root.service.setMonitorVolume(percent) }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.service && root.service.micMuted ? "󰍭" : "󰍬"
    active: root.opened || (root.service && root.service.micAvailable && !root.service.micMuted)
    tooltipText: !root.service || !root.service.micAvailable
      ? "Scarlett microphone unavailable"
      : (root.service.micMuted
          ? "Scarlett microphone muted · right-click to unmute"
          : "Scarlett microphone live · right-click to mute")

    onPressed: function(code) {
      if (!root.service) return
      if (code === Qt.RightButton) root.service.toggleMic()
      else if (code === Qt.MiddleButton && root.service.monitorAvailable) root.service.toggleMonitor()
      else root.toggle()
    }

    onWheelMoved: function(delta) {
      root.adjustMonitorVolume(delta > 0 ? 5 : -5)
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(380))
    contentHeight: panel.fittedContentHeight(panelColumn.implicitHeight, Style.space(440))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onMoveRequested: function(dx, dy) {
        root.cursorActive = true
        if (dy !== 0) root.focusRow = Math.max(0, Math.min(1, root.focusRow + dy))
        else if (dx !== 0 && root.focusRow === 1) root.adjustMonitorVolume(dx * 5)
      }
      onActivateRequested: root.activateCursor()
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(text) {
        if ((text === "m" || text === "M") && root.service) root.service.toggleMic()
        if ((text === "h" || text === "H") && root.service && root.service.monitorAvailable)
          root.service.toggleMonitor()
        if ((text === "r" || text === "R") && root.service) root.service.refresh()
      }

      ScrollView {
        id: scrollArea
        anchors.fill: parent
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical.policy: ScrollBar.AlwaysOff

        Column {
          id: panelColumn
          width: scrollArea.availableWidth
          spacing: Style.space(14)

          ControlRow {
            iconText: root.service && root.service.micMuted ? "󰍭" : "󰍬"
            title: "Microphone"
            subtitle: !root.service || !root.service.micAvailable ? "Scarlett input unavailable"
              : (root.service.micMuted ? "Muted for applications and calls" : "Live to applications and calls")
            checked: root.service ? root.service.micAvailable && !root.service.micMuted : false
            available: root.service ? root.service.micAvailable : false
            busy: root.service ? root.service.busy : false
            hasCursor: root.cursorActive && root.focusRow === 0
            onToggled: if (root.service) root.service.toggleMic()
          }

          Text {
            width: parent.width
            text: root.service ? root.service.micDevice : "Scarlett microphone"
            color: Qt.darker(root.foreground, 1.5)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
          }

          PanelSeparator { foreground: root.foreground }

          ControlRow {
            iconText: root.service && root.service.monitorEnabled ? "󰋋" : "󰟎"
            title: "Hear myself"
            subtitle: !root.service || !root.service.monitorAvailable ? "Hardware monitoring unavailable"
              : (root.service.monitorEnabled
                  ? root.service.monitorVolume + "% in Scarlett headphones"
                  : "Off · microphone can still be live")
            checked: root.service ? root.service.monitorEnabled : false
            available: root.service ? root.service.monitorAvailable : false
            busy: root.service ? root.service.busy : false
            hasCursor: root.cursorActive && root.focusRow === 1
            onToggled: if (root.service) root.service.toggleMonitor()
          }

          Item {
            width: parent.width
            implicitHeight: Math.max(volumeSlider.implicitHeight, volumePercent.implicitHeight)
            visible: root.service ? root.service.monitorAvailable : false

            PanelSlider {
              id: volumeSlider
              anchors.left: parent.left
              anchors.right: volumePercent.left
              anchors.rightMargin: Style.space(12)
              anchors.verticalCenter: parent.verticalCenter
              bar: root.bar
              value: root.service ? root.service.monitorVolume / 100 : 0
              minimum: 0
              maximum: 1
              step: 0.05
              enabled: root.service ? root.service.monitorAvailable && !root.service.busy : false
              onReleased: function(value) {
                if (root.service) root.service.setMonitorVolume(value * 100)
              }
              onRightClicked: if (root.service) root.service.toggleMonitor()
            }

            Text {
              id: volumePercent
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              text: Math.round((volumeSlider.dragging ? volumeSlider.liveValue : volumeSlider.value) * 100) + "%"
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
              font.bold: true
              width: Style.space(48)
              horizontalAlignment: Text.AlignRight
            }
          }

          Text {
            width: parent.width
            visible: root.service ? root.service.message !== "" : false
            text: root.service ? root.service.message : ""
            color: Color.urgent
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.Wrap
          }

          Text {
            width: parent.width
            visible: root.service ? root.service.lastError !== "" : false
            text: root.service ? root.service.lastError : ""
            color: Color.urgent
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.Wrap
          }

          Text {
            width: parent.width
            text: "Right-click: mute mic · Middle-click: hear myself · Scroll: monitor level"
            color: Qt.darker(root.foreground, 1.6)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            horizontalAlignment: Text.AlignHCenter
          }
        }
      }
    }
  }

  component ControlRow: Item {
    id: control
    property string iconText: "󰍬"
    property string title: ""
    property string subtitle: ""
    property bool checked: false
    property bool available: true
    property bool busy: false
    property bool hasCursor: false
    signal toggled()

    width: parent ? parent.width : 0
    implicitHeight: Math.max(controlIcon.implicitHeight, controlLabels.implicitHeight, controlSwitch.implicitHeight)

    Text {
      id: controlIcon
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      text: control.iconText
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.display
      opacity: control.available ? 1.0 : 0.5
    }

    Column {
      id: controlLabels
      anchors.left: controlIcon.right
      anchors.leftMargin: Style.space(14)
      anchors.right: controlSwitch.left
      anchors.rightMargin: Style.space(12)
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(2)

      Text {
        width: parent.width
        text: control.title
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.title
        font.bold: true
        elide: Text.ElideRight
      }

      Text {
        width: parent.width
        text: control.subtitle
        color: Qt.darker(root.foreground, 1.4)
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }
    }

    ToggleSwitch {
      id: controlSwitch
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      checked: control.checked
      busy: control.busy
      enabled: control.available
      foreground: root.foreground
      hasCursor: control.hasCursor
      onToggled: control.toggled()
    }
  }
}
