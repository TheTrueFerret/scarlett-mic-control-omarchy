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
  property string expandedRoute: ""
  property int choiceCursor: 0
  property string confirmDelete: ""

  readonly property var presets: service ? service.presets : []
  readonly property bool routingAvailable: service ? service.routingAvailable : false
  readonly property bool showAllRoutes: service ? service.routingView === "all" : false
  // Shown in panel order: outputs first, then what the computer records.
  readonly property var visibleRoutes: {
    var routing = service ? service.routing : []
    var shown = showAllRoutes ? routing
      : routing.filter(function(row) { return row.section === "hear" && !row.off })
    return shown.filter(function(row) { return row.section === "hear" })
      .concat(shown.filter(function(row) { return row.section === "record" }))
  }
  // Cursor rows: 0 microphone, 1 hear myself, 2 mixer app, 3 show all, one
  // per visible route, save preset, then one per preset.
  readonly property int firstRouteRow: 4
  readonly property int saveRow: firstRouteRow + (routingAvailable ? visibleRoutes.length : 0)
  readonly property int firstPresetRow: saveRow + 1
  readonly property int lastRow: routingAvailable ? saveRow + presets.length : 2
  readonly property var cursorRoute: focusRow >= firstRouteRow && focusRow < saveRow
    ? visibleRoutes[focusRow - firstRouteRow] : null
  readonly property int hiddenRoutes: (service ? service.routing.length : 0) - visibleRoutes.length
  readonly property var glyphs: ({
    "in": String.fromCodePoint(0xF036C), "pc": String.fromCodePoint(0xF0322),
    "spdif": String.fromCodePoint(0xF0200), "adat": String.fromCodePoint(0xF0200),
    "mix": String.fromCodePoint(0xF062E), "out": String.fromCodePoint(0xF057E),
    "phones": String.fromCodePoint(0xF02CB), "rec": String.fromCodePoint(0xF044A),
    "from": String.fromCodePoint(0xF004D), "check": String.fromCodePoint(0xF012C)
  })

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function adjustMonitorVolume(delta) {
    if (!service || !service.monitorAvailable || service.busy) return
    service.setMonitorVolume(Math.max(0, Math.min(100, service.monitorVolume + delta)))
  }

  function activateCursor() {
    if (!service || service.busy) return
    if (confirmDelete !== "") { deleteConfirmed(); return }
    if (focusRow === 0 && service.micAvailable) service.toggleMic()
    else if (focusRow === 1 && service.monitorAvailable) service.toggleMonitor()
    else if (focusRow === 2) activateMixerApp()
    else if (focusRow === 3) toggleShowAll()
    else if (cursorRoute) activateRoute(cursorRoute)
    else if (focusRow === saveRow) startSavingPreset()
    else if (focusRow >= firstPresetRow) applyPreset(focusRow - firstPresetRow)
  }

  // Enter opens a route's choices on the current one; Enter again applies.
  function activateRoute(row) {
    var choices = row.choices || []
    if (choices.length === 0) return
    if (expandedRoute !== row.key) {
      toggleRoute(row.key)
      return
    }
    chooseRoute(row.key, choices[Math.max(0, Math.min(choices.length - 1, choiceCursor))])
  }

  function moveCursor(dx, dy) {
    cursorActive = true
    confirmDelete = ""
    if (expandedRoute !== "" && cursorRoute && cursorRoute.key === expandedRoute && dx !== 0) {
      choiceCursor = Math.max(0, Math.min(cursorRoute.choices.length - 1, choiceCursor + dx))
      return
    }
    if (dy !== 0) {
      expandedRoute = ""
      focusRow = Math.max(0, Math.min(lastRow, focusRow + dy))
    } else if (dx !== 0 && focusRow === 1) {
      adjustMonitorVolume(dx * 5)
    }
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

  function toggleShowAll() {
    if (!service || !routingAvailable) return
    expandedRoute = ""
    service.setRoutingView(showAllRoutes ? "compact" : "all")
  }

  function toggleRoute(key) {
    expandedRoute = expandedRoute === key ? "" : key
    choiceCursor = 0
    var row = visibleRoutes.filter(function(item) { return item.key === key })[0]
    if (row) {
      for (var i = 0; i < row.choices.length; i++) if (row.choices[i].current) choiceCursor = i
      focusRow = firstRouteRow + visibleRoutes.indexOf(row)
    }
  }

  function chooseRoute(rowKey, choice) {
    expandedRoute = ""
    if (service && !choice.current) service.setRoute(rowKey, choice.key)
  }

  function applyPreset(index) {
    if (!service || service.busy || index < 0 || index >= presets.length) return
    if (presets[index].compatible) service.applyPreset(presets[index].name)
  }

  function askDeletePreset(index) {
    if (index >= 0 && index < presets.length) confirmDelete = presets[index].name
  }

  function deleteConfirmed() {
    if (service && confirmDelete !== "") service.deletePreset(confirmDelete)
    confirmDelete = ""
  }

  function startSavingPreset() {
    if (!service || !routingAvailable) return
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

  // Escape backs out of an open picker or question before closing the panel.
  function cancelOrClose() {
    if (expandedRoute !== "") expandedRoute = ""
    else if (confirmDelete !== "") confirmDelete = ""
    else close()
  }

  // The chain after a destination, read right to left as signal flow:
  // the mix it plays (if any), then what that mix is made of.
  function chainItems(row) {
    var items = [{ role: "arrow" }]
    if (row.off) return items.concat([{ role: "note", label: "Off" }])
    if (row.same_as) {
      return items.concat([
        { role: "via", label: row.via, kind: "mix", hint: row.via_hint },
        { role: "note", label: "same as " + row.same_as }
      ])
    }
    if (row.via) {
      items.push({ role: "via", label: row.via, kind: "mix", hint: row.via_hint })
      items.push({ role: "arrow" })
    }
    var sources = row.sources || []
    for (var i = 0; i < Math.min(sources.length, 4); i++)
      items.push({ role: "source", label: sources[i].label, kind: sources[i].kind, db: sources[i].db, hint: sources[i].hint })
    if (sources.length > 4) {
      var rest = sources.slice(4).map(function(source) { return source.label }).join(", ")
      items.push({ role: "note", label: "+" + (sources.length - 4) + " more", hint: rest })
    }
    if (sources.length === 0) items.push({ role: "note", label: "Silent", hint: "Nothing is mixed in" })
    return items
  }

  // Choices grouped by kind, each remembering its place in the flat list
  // the keyboard cursor walks.
  function choiceGroups(choices) {
    var groups = []
    for (var i = 0; i < choices.length; i++) {
      var title = choices[i].group || ""
      var last = groups.length ? groups[groups.length - 1] : null
      if (!last || last.title !== title) {
        last = { title: title, items: [] }
        groups.push(last)
      }
      last.items.push({ choice: choices[i], index: i })
    }
    return groups
  }

  onOpenedChanged: if (opened) {
    cursorActive = false
    focusRow = 0
    savingPreset = false
    expandedRoute = ""
    confirmDelete = ""
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
    function nextPreset(): void { if (root.service) root.service.applyNextPreset() }
    function savePreset(name: string): void { if (root.service) root.service.savePreset(name) }
    function deletePreset(name: string): void { if (root.service) root.service.deletePreset(name) }
    function setRoute(row: string, choice: string): void { if (root.service) root.service.setRoute(row, choice) }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.service && root.service.micMuted ? "󰍭" : "󰍬"
    active: root.opened || (root.service && root.service.micAvailable && !root.service.micMuted)
    tooltipText: (!root.service || !root.service.micAvailable
      ? "Scarlett microphone unavailable"
      : (root.service.micMuted
          ? "Scarlett microphone muted · right-click to unmute"
          : "Scarlett microphone live · right-click to mute"))
      + (root.service && root.service.activePreset ? "\nPreset: " + root.service.activePreset : "")

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
    contentHeight: panel.fittedContentHeight(panelColumn.implicitHeight, Style.space(760))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: presetName.activeFocus
      onMoveRequested: function(dx, dy) { root.moveCursor(dx, dy) }
      onActivateRequested: root.activateCursor()
      onCloseRequested: root.cancelOrClose()
      onDeleteRequested: if (root.focusRow >= root.firstPresetRow) root.askDeletePreset(root.focusRow - root.firstPresetRow)
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(text) {
        if ((text === "m" || text === "M") && root.service) root.service.toggleMic()
        if ((text === "h" || text === "H") && root.service && root.service.monitorAvailable)
          root.service.toggleMonitor()
        if ((text === "r" || text === "R") && root.service) root.service.refresh()
        if (text === "o" || text === "O") root.activateMixerApp()
        if (text === "a" || text === "A") root.toggleShowAll()
        if (text === "s" || text === "S") root.startSavingPreset()
        if (text === "n" || text === "N") { if (root.service) root.service.applyNextPreset() }
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
            implicitHeight: Math.max(routingHeader.implicitHeight, routingActions.implicitHeight)

            PanelSectionHeader {
              id: routingHeader
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
              text: "ROUTING"
              foreground: root.foreground
              fontFamily: root.fontFamily
            }

            Row {
              id: routingActions
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(4)

              SmallButton {
                visible: root.routingAvailable && (root.showAllRoutes || root.hiddenRoutes > 0)
                text: root.showAllRoutes ? "Show less" : "Show all (" + root.hiddenRoutes + ")"
                tooltipText: root.showAllRoutes ? "Only show outputs in use"
                  : "Also show what the computer records and unused outputs"
                hasCursor: root.cursorActive && root.focusRow === 3
                onClicked: root.toggleShowAll()
              }

              SmallButton {
                visible: root.service ? root.service.mixerAppInstalled || root.service.mixerAppInstallable : false
                text: root.service && root.service.mixerAppInstalled ? "Open mixer" : "Install mixer"
                iconText: root.service && root.service.mixerAppInstalled
                  ? String.fromCodePoint(0xF03CC) : String.fromCodePoint(0xF01DA)
                tooltipText: root.service && root.service.mixerAppInstalled
                  ? "Edit mixes and levels in ALSA Scarlett Control Panel"
                  : "Install ALSA Scarlett Control Panel (alsa-scarlett-gui) in a terminal"
                hasCursor: root.cursorActive && root.focusRow === 2
                onClicked: root.activateMixerApp()
              }
            }
          }

          Text {
            width: parent.width
            visible: !root.routingAvailable
            text: root.service && root.service.mixerAppInstalled
              ? "This interface does not expose software routing. Use the mixer app or the front panel."
              : "This interface does not expose software routing, or the mixer app is needed to see it."
            color: Qt.darker(root.foreground, 1.4)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.Wrap
          }

          Text {
            width: parent.width
            visible: root.routingAvailable && root.visibleRoutes.length > 0
            text: "Click an output to change what it plays."
            color: Qt.darker(root.foreground, 1.6)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          RouteGroup { title: "Outputs"; section: "hear" }
          RouteGroup { title: "To computer"; section: "record" }

          Item {
            width: parent.width
            visible: root.routingAvailable
            implicitHeight: Math.max(presetHeader.implicitHeight, saveButton.implicitHeight)

            Row {
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(8)

              PanelSectionHeader {
                id: presetHeader
                anchors.verticalCenter: parent.verticalCenter
                text: "PRESETS"
                foreground: root.foreground
                fontFamily: root.fontFamily
              }

              Text {
                anchors.verticalCenter: parent.verticalCenter
                visible: root.presets.length > 0 && root.service && root.service.activePreset === ""
                text: "current routing not saved"
                color: Qt.darker(root.foreground, 1.6)
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }
            }

            SmallButton {
              id: saveButton
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              iconText: String.fromCodePoint(0xF0193)
              text: "Save current"
              tooltipText: "Save the interface's current routing and mix as a preset"
              enabled: root.service ? !root.service.busy : false
              hasCursor: root.cursorActive && root.focusRow === root.saveRow
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
            visible: root.routingAvailable && root.presets.length > 0
            spacing: Style.space(6)

            Repeater {
              model: root.presets

              SmallButton {
                required property var modelData
                required property int index
                text: (index < 9 ? (index + 1) + "  " : "") + modelData.name
                tooltipText: !modelData.compatible ? "Saved from a different interface · right-click to delete"
                  : (modelData.active ? "Current routing matches this preset · right-click to delete"
                                      : "Apply this routing · right-click to delete")
                selected: modelData.active
                enabled: modelData.compatible && root.service && !root.service.busy
                hasCursor: root.cursorActive && root.focusRow === index + root.firstPresetRow
                onClicked: root.applyPreset(index)
                onRightClicked: root.askDeletePreset(index)
              }
            }
          }

          Item {
            width: parent.width
            visible: root.confirmDelete !== ""
            implicitHeight: Math.max(deleteQuestion.implicitHeight, deleteActions.implicitHeight)

            Text {
              id: deleteQuestion
              anchors.left: parent.left
              anchors.right: deleteActions.left
              anchors.verticalCenter: parent.verticalCenter
              text: "Delete “" + root.confirmDelete + "”?"
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
              elide: Text.ElideRight
            }

            Row {
              id: deleteActions
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(4)

              SmallButton { text: "Delete"; onClicked: root.deleteConfirmed() }
              SmallButton { text: "Cancel"; onClicked: root.confirmDelete = "" }
            }
          }

          Text {
            width: parent.width
            visible: root.routingAvailable && root.presets.length === 0 && !root.savingPreset
            text: "Save the current routing here, or use File › Save Configuration in the mixer app to save into "
              + (root.service ? root.service.presetsDir.replace(/^\/home\/[^/]+/, "~") : "") + "."
            color: Qt.darker(root.foreground, 1.4)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.Wrap
          }

          Text {
            width: parent.width
            visible: root.service ? root.service.notice !== "" : false
            text: root.glyphs.check + "  " + (root.service ? root.service.notice : "")
            color: Color.accent
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
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

          // Key hints only matter once the keyboard is in use.
          Text {
            width: parent.width
            visible: root.cursorActive
            text: "Enter: change an output · ←/→ pick · Esc back · X delete\n"
              + "M mute · H monitor · O mixer · A all · S save · N next"
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

  component SmallButton: Button {
    foreground: root.foreground
    fontFamily: root.fontFamily
    fontSize: Style.font.bodySmall
    iconSize: Style.font.bodySmall
    horizontalPadding: Style.space(8)
    verticalPadding: Style.space(3)
  }

  component RouteGroup: Column {
    id: group
    property string title: ""
    property string section: ""
    readonly property var rows: root.visibleRoutes.filter(function(row) { return row.section === group.section })
    // Destinations sit in one column so the outputs can be scanned top to bottom.
    readonly property real destinationWidth: Style.space(96)

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

      Column {
        id: routeRow
        required property var modelData
        readonly property bool expanded: root.expandedRoute === modelData.key
        readonly property bool changeable: (modelData.choices || []).length > 0
        width: group.width
        spacing: Style.space(6)

        Item {
          width: parent.width
          implicitHeight: Math.max(destination.implicitHeight, chain.implicitHeight)

          RouteChip {
            id: destination
            anchors.left: parent.left
            anchors.top: parent.top
            role: "destination"
            label: routeRow.modelData.destination
            kind: routeRow.modelData.kind
            hint: routeRow.modelData.destination_hint + (routeRow.changeable ? " · click to change" : "")
            clickable: routeRow.changeable
            selected: routeRow.expanded
            hasCursor: root.cursorActive && root.cursorRoute !== null && root.cursorRoute.key === routeRow.modelData.key
            onClicked: root.toggleRoute(routeRow.modelData.key)
          }

          Flow {
            id: chain
            anchors.left: parent.left
            anchors.leftMargin: Math.max(group.destinationWidth, destination.width + Style.space(4))
            anchors.right: parent.right
            spacing: Style.space(4)

            Repeater {
              model: root.chainItems(routeRow.modelData)
              RouteChip {
                required property var modelData
                role: modelData.role
                label: modelData.label || ""
                kind: modelData.kind || ""
                hint: modelData.hint || ""
                db: modelData.db === undefined ? null : modelData.db
              }
            }
          }
        }

        // Inline picker rather than a popup: it can never be clipped by the
        // panel's edge, and it keeps the choice next to the row it changes.
        // One line per kind of source keeps large interfaces scannable.
        Column {
          visible: routeRow.expanded
          width: parent.width
          spacing: Style.space(4)

          Repeater {
            model: routeRow.expanded ? root.choiceGroups(routeRow.modelData.choices) : []

            Item {
              id: choiceGroup
              required property var modelData
              width: parent.width
              implicitHeight: choiceFlow.implicitHeight

              Text {
                anchors.right: choiceFlow.left
                anchors.rightMargin: Style.space(8)
                y: Style.space(4)
                text: choiceGroup.modelData.title
                color: Qt.darker(root.foreground, 1.6)
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }

              Flow {
                id: choiceFlow
                anchors.left: parent.left
                anchors.leftMargin: group.destinationWidth
                anchors.right: parent.right
                spacing: Style.space(4)

                Repeater {
                  model: choiceGroup.modelData.items
                  RouteChip {
                    required property var modelData
                    role: "choice"
                    hasCursor: root.cursorActive && modelData.index === root.choiceCursor
                    label: modelData.choice.label
                    kind: modelData.choice.kind
                    selected: modelData.choice.current
                    clickable: true
                    hint: modelData.choice.current ? "Playing now" : "Play " + modelData.choice.label + " here"
                    onClicked: root.chooseRoute(routeRow.modelData.key, modelData.choice)
                  }
                }
              }
            }
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
    property string hint: ""
    property var db: null
    property bool clickable: false
    property bool selected: false
    property bool hasCursor: false
    signal clicked()

    readonly property bool arrow: role === "arrow"
    readonly property bool note: role === "note"
    readonly property bool emphasis: role === "destination" || selected
    readonly property bool hot: clickable && (chipMouse.containsMouse || hasCursor)
    readonly property color tint: emphasis ? Color.accent : root.foreground

    // The hidden half of a chip reports no size, so each mode measures its own.
    implicitWidth: arrow ? arrowGlyph.implicitWidth : chipRow.implicitWidth + Style.space(10)
    implicitHeight: (arrow ? arrowGlyph.implicitHeight : chipRow.implicitHeight) + Style.space(6)
    radius: Math.min(Style.cornerRadius, height / 2)
    color: arrow || note ? "transparent"
      : Qt.rgba(tint.r, tint.g, tint.b, hot ? 0.24 : (emphasis ? 0.18 : (role === "via" ? 0.12 : 0.06)))
    border.width: arrow || note ? 0 : 1
    border.color: Qt.rgba(tint.r, tint.g, tint.b, hot || selected ? 0.8 : (emphasis ? 0.55 : 0.2))

    Text {
      id: arrowGlyph
      anchors.centerIn: parent
      visible: chip.arrow
      text: root.glyphs.from
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
        color: chip.note ? Qt.darker(root.foreground, 1.5) : root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: chip.emphasis
        font.italic: chip.note
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

    MouseArea {
      id: chipMouse
      anchors.fill: parent
      enabled: !chip.arrow
      hoverEnabled: true
      cursorShape: chip.clickable ? Qt.PointingHandCursor : Qt.ArrowCursor
      onClicked: if (chip.clickable) chip.clicked()
    }

    PanelToolTip {
      visible: chip.hint !== "" && chipMouse.containsMouse
      text: chip.hint
      fontFamily: root.fontFamily
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
