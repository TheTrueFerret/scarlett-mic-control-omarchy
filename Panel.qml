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
  property bool savingPreset: false

  // Rows: 0 microphone, 1 hear myself, 2 mixer app, then one per preset.
  readonly property var presets: service ? service.presets : []
  readonly property int lastRow: 2 + (service && service.routingAvailable ? presets.length : 0)
  readonly property var glyphs: ({
    "in": String.fromCodePoint(0xF036C), "pc": String.fromCodePoint(0xF0322),
    "spdif": String.fromCodePoint(0xF0200), "adat": String.fromCodePoint(0xF0200),
    "mix": String.fromCodePoint(0xF062E), "out": String.fromCodePoint(0xF04C3),
    "phones": String.fromCodePoint(0xF02CB), "rec": String.fromCodePoint(0xF044A),
    "arrow": String.fromCodePoint(0xF0054)
  })

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
    else if (focusRow === 2) activateMixerApp()
    else if (focusRow > 2) applyPreset(focusRow - 3)
  }

  function activateMixerApp() {
    if (!service) return
    if (service.mixerAppInstalled) {
      service.openMixerApp()
      close()
    } else if (service.mixerAppInstallable) {
      service.installMixerApp()
      close()
    }
  }

  function applyPreset(index) {
    if (!service || service.busy || index < 0 || index >= presets.length) return
    if (presets[index].compatible) service.applyPreset(presets[index].name)
  }

  function startSavingPreset() {
    if (!service || !service.routingAvailable) return
    presetName.text = "Preset " + (presets.length + 1)
    savingPreset = true
    Qt.callLater(function() { presetName.forceActiveFocus(); presetName.selectAll() })
  }

  function finishSavingPreset(save) {
    var name = presetName.text.trim()
    if (save && name && service) service.savePreset(name)
    savingPreset = false
    keyCatcher.forceActiveFocus()
  }

  // One row of the routing view as chips: sources, the mix they pass
  // through (if any), and the output or computer channel they end up in.
  function routeItems(row) {
    var items = []
    var sources = row.sources || []
    for (var i = 0; i < Math.min(sources.length, 4); i++)
      items.push({ role: "source", label: sources[i].label, kind: sources[i].kind, db: sources[i].db })
    if (sources.length > 4)
      items.push({ role: "source", label: "+" + (sources.length - 4) + " more", kind: "", db: null })
    if (sources.length === 0)
      items.push({ role: "source", label: "Silent", kind: "", db: null })
    items.push({ role: "arrow" })
    if (row.via) {
      items.push({ role: "via", label: row.via, kind: "mix", db: null })
      items.push({ role: "arrow" })
    }
    var kind = row.section === "record" ? "rec" : (row.destination === "Phones" ? "phones" : "out")
    items.push({ role: "destination", label: row.destination, kind: kind, db: null })
    return items
  }

  function routesIn(section) {
    var routing = service ? service.routing : []
    return routing.filter(function(row) { return row.section === section })
  }

  onOpenedChanged: if (opened) {
    cursorActive = false
    focusRow = 0
    savingPreset = false
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
    function openMixer(): void { if (root.service) root.service.openMixerApp() }
    function applyPreset(name: string): void { if (root.service) root.service.applyPreset(name) }
    function savePreset(name: string): void { if (root.service) root.service.savePreset(name) }
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
    contentWidth: panel.fittedContentWidth(Style.space(420))
    contentHeight: panel.fittedContentHeight(panelColumn.implicitHeight, Style.space(640))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: presetName.activeFocus
      onMoveRequested: function(dx, dy) {
        root.cursorActive = true
        if (dy !== 0) root.focusRow = Math.max(0, Math.min(root.lastRow, root.focusRow + dy))
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
        if (text === "o" || text === "O") root.activateMixerApp()
        if (text === "s" || text === "S") root.startSavingPreset()
        if (text >= "1" && text <= "9") root.applyPreset(Number(text) - 1)
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

          PanelSeparator { foreground: root.foreground }

          Item {
            width: parent.width
            implicitHeight: Math.max(routingHeader.implicitHeight, mixerButton.implicitHeight)

            PanelSectionHeader {
              id: routingHeader
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
              text: "ROUTING"
              foreground: root.foreground
              fontFamily: root.fontFamily
            }

            Button {
              id: mixerButton
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              visible: root.service ? root.service.mixerAppInstalled || root.service.mixerAppInstallable : false
              text: root.service && root.service.mixerAppInstalled ? "Open mixer" : "Install mixer"
              iconText: root.service && root.service.mixerAppInstalled
                ? String.fromCodePoint(0xF03CC) : String.fromCodePoint(0xF01DA)
              tooltipText: root.service && root.service.mixerAppInstalled
                ? "Edit the full routing in ALSA Scarlett Control Panel"
                : "Install ALSA Scarlett Control Panel (alsa-scarlett-gui) in a terminal"
              foreground: root.foreground
              fontFamily: root.fontFamily
              fontSize: Style.font.bodySmall
              iconSize: Style.font.bodySmall
              horizontalPadding: Style.space(8)
              verticalPadding: Style.space(3)
              hasCursor: root.cursorActive && root.focusRow === 2
              onClicked: root.activateMixerApp()
            }
          }

          Text {
            width: parent.width
            visible: root.service ? !root.service.routingAvailable : true
            text: root.service && root.service.mixerAppInstalled
              ? "This interface does not expose software routing. Use the mixer app or the front panel."
              : "This interface does not expose software routing, or the mixer app is needed to see it."
            color: Qt.darker(root.foreground, 1.4)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.Wrap
          }

          RouteGroup { title: "Outputs"; rows: root.routesIn("hear") }
          RouteGroup { title: "To computer"; rows: root.routesIn("record") }

          Item {
            width: parent.width
            visible: root.service ? root.service.routingAvailable : false
            implicitHeight: Math.max(presetHeader.implicitHeight, saveButton.implicitHeight)

            PanelSectionHeader {
              id: presetHeader
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
              text: "PRESETS"
              foreground: root.foreground
              fontFamily: root.fontFamily
            }

            Button {
              id: saveButton
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              iconText: String.fromCodePoint(0xF0193)
              text: "Save current"
              tooltipText: "Save the interface's current routing and mix as a preset"
              foreground: root.foreground
              fontFamily: root.fontFamily
              fontSize: Style.font.bodySmall
              iconSize: Style.font.bodySmall
              horizontalPadding: Style.space(8)
              verticalPadding: Style.space(3)
              enabled: root.service ? !root.service.busy : false
              onClicked: root.startSavingPreset()
            }
          }

          TextField {
            id: presetName
            width: parent.width
            visible: root.savingPreset
            placeholderText: "Preset name, then Enter"
            foreground: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            maximumLength: 48
            validator: RegularExpressionValidator { regularExpression: /[A-Za-z0-9][A-Za-z0-9 _.-]*/ }
            onAccepted: root.finishSavingPreset(true)
            Keys.onEscapePressed: function(event) { root.finishSavingPreset(false); event.accepted = true }
          }

          Flow {
            width: parent.width
            visible: root.service ? root.service.routingAvailable && root.presets.length > 0 : false
            spacing: Style.space(6)

            Repeater {
              model: root.presets

              Button {
                required property var modelData
                required property int index
                text: (index < 9 ? (index + 1) + "  " : "") + modelData.name
                tooltipText: !modelData.compatible ? "Saved from a different interface"
                  : (modelData.active ? "Current routing matches this preset" : "Apply this routing")
                selected: modelData.active
                enabled: modelData.compatible && root.service && !root.service.busy
                foreground: root.foreground
                fontFamily: root.fontFamily
                fontSize: Style.font.bodySmall
                horizontalPadding: Style.space(8)
                verticalPadding: Style.space(3)
                hasCursor: root.cursorActive && root.focusRow === index + 3
                onClicked: root.applyPreset(index)
              }
            }
          }

          Text {
            width: parent.width
            visible: root.service ? root.service.routingAvailable && root.presets.length === 0 && !root.savingPreset : false
            text: "Save the current routing here, or use File › Save Configuration in the mixer app to save into "
              + (root.service ? root.service.presetsDir.replace(/^\/home\/[^/]+/, "~") : "") + "."
            color: Qt.darker(root.foreground, 1.4)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.Wrap
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
            text: "Right-click: mute · Middle-click: hear myself · Scroll: level\n"
              + "O: open mixer · S: save preset · 1–9: apply preset"
            color: Qt.darker(root.foreground, 1.6)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
          }
        }
      }
    }
  }

  component RouteGroup: Column {
    id: group
    property string title: ""
    property var rows: []

    width: parent ? parent.width : 0
    spacing: Style.space(6)
    visible: rows.length > 0

    Text {
      text: group.title
      color: Qt.darker(root.foreground, 1.5)
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }

    Repeater {
      model: group.rows

      Flow {
        id: routeRow
        required property var modelData
        width: group.width
        spacing: Style.space(4)

        Repeater {
          model: root.routeItems(routeRow.modelData)
          RouteChip {
            required property var modelData
            role: modelData.role
            label: modelData.label || ""
            kind: modelData.kind || ""
            db: modelData.db === undefined ? null : modelData.db
          }
        }
      }
    }
  }

  component RouteChip: Rectangle {
    id: chip
    property string role: "source"
    property string label: ""
    property string kind: ""
    property var db: null
    readonly property bool arrow: role === "arrow"
    readonly property bool destination: role === "destination"
    readonly property color tint: destination ? Color.accent : root.foreground

    // The hidden half of a chip reports no size, so each mode measures its own.
    implicitWidth: arrow ? arrowGlyph.implicitWidth : chipRow.implicitWidth + Style.space(10)
    implicitHeight: (arrow ? arrowGlyph.implicitHeight : chipRow.implicitHeight) + Style.space(6)
    radius: Math.min(Style.cornerRadius, height / 2)
    color: arrow ? "transparent" : Qt.rgba(tint.r, tint.g, tint.b, destination ? 0.18 : (role === "via" ? 0.12 : 0.06))
    border.width: arrow ? 0 : 1
    border.color: Qt.rgba(tint.r, tint.g, tint.b, destination ? 0.55 : 0.2)

    Text {
      id: arrowGlyph
      anchors.centerIn: parent
      visible: chip.arrow
      text: root.glyphs.arrow
      color: Qt.darker(root.foreground, 1.6)
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
    }

    Row {
      id: chipRow
      anchors.centerIn: parent
      visible: !chip.arrow
      spacing: Style.space(3)

      Text {
        visible: text !== ""
        anchors.verticalCenter: parent.verticalCenter
        text: root.glyphs[chip.kind] || ""
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
      }

      Text {
        anchors.verticalCenter: parent.verticalCenter
        text: chip.label
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: chip.destination
      }

      Text {
        visible: chip.db !== null && chip.db !== 0
        anchors.verticalCenter: parent.verticalCenter
        text: (chip.db > 0 ? "+" : "−") + Math.abs(chip.db) + " dB"
        color: Qt.darker(root.foreground, 1.5)
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
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
