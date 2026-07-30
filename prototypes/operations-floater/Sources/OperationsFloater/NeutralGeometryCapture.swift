import AppKit
import Combine
import CoreGraphics
import Foundation
import SwiftUI

enum NeutralGeometryCaptureMode: String, Codable, Sendable {
    case disarmed
    case armed
    case recording
    case paused
    case review

    var displayName: String { rawValue.uppercased() }
}

struct NeutralGeometryWindow: Identifiable, Equatable, Sendable {
    let id: CGWindowID
    let ownerPID: pid_t
    let ownerName: String
    let bounds: CGRect

    var displayName: String {
        "\(ownerName) · \(Int(bounds.width))×\(Int(bounds.height))"
    }
}

struct NeutralGeometryCaptureSnapshot: Equatable, Sendable {
    let events: [ConversationModuleEvent]
    let window: ConversationModuleWindowContext
}

struct NeutralGeometryCaptureExport: Codable, Equatable, Sendable {
    static let schema = "operations-floater-relative-xy-capture/v1"

    struct Event: Codable, Equatable, Sendable {
        let ordinal: Int
        let kind: ConversationModuleEventKind
        let pointerPhase: ConversationPointerPhase?
        let normalizedX: Double?
        let normalizedY: Double?
        let keyPhase: ConversationKeyPhase?
        let keyCode: Int?
        let modifierFlags: UInt64?
        let buttonNumber: Int?
        let scrollDeltaX: Double?
        let scrollDeltaY: Double?
        let elapsedMilliseconds: Int?
    }

    let schema: String
    let moduleID: String
    let windowBindingID: String
    let windowWidth: Int
    let windowHeight: Int
    let eventCount: Int
    let droppedEventCount: Int
    let provenanceSourceID: String
    let buildDigest: String
    let selectedWindowIdentityPersisted: Bool
    let charactersRecovered: Bool
    let screenCaptureUsed: Bool
    let ocrUsed: Bool
    let events: [Event]
}

enum NeutralGeometryCaptureError: LocalizedError, Equatable {
    case noWindow
    case windowChanged
    case inputMonitoringRequired
    case reviewRequired
    case noEvents
    case invalidProvenance

    var errorDescription: String? {
        switch self {
        case .noWindow:
            "Select one visible window before recording."
        case .windowChanged:
            "The selected window changed or is no longer the active window."
        case .inputMonitoringRequired:
            "Allow Operations Floater in Privacy & Security → Input Monitoring, then retry."
        case .reviewRequired:
            "Stop the recorder before exporting."
        case .noEvents:
            "No selected-window input events are available to export."
        case .invalidProvenance:
            "The relative XY module provenance is unavailable or invalid."
        }
    }
}

struct NeutralGeometryRawEvent: Equatable, Sendable {
    enum Kind: Equatable, Sendable {
        case pointer(ConversationPointerPhase, Int)
        case scroll(Double, Double)
        case key(ConversationKeyPhase, Int, UInt64)
    }

    let kind: Kind
    let location: CGPoint?
    let timestampNanoseconds: UInt64
}

enum NeutralGeometryWindowCatalog {
    static func visibleWindows(
        excludingPID: pid_t = ProcessInfo.processInfo.processIdentifier
    ) -> [NeutralGeometryWindow] {
        guard let values = CGWindowListCopyWindowInfo(
            [.optionOnScreenOnly, .excludeDesktopElements],
            kCGNullWindowID
        ) as? [[String: Any]] else {
            return []
        }
        return values.compactMap { value in
            guard let number = value[kCGWindowNumber as String] as? NSNumber,
                  let pid = value[kCGWindowOwnerPID as String] as? NSNumber,
                  let layer = value[kCGWindowLayer as String] as? NSNumber,
                  let owner = value[kCGWindowOwnerName as String] as? String,
                  let boundsValue = value[kCGWindowBounds as String]
                    as? [String: Any],
                  let bounds = CGRect(
                      dictionaryRepresentation: boundsValue as CFDictionary
                  ),
                  layer.intValue == 0,
                  pid.int32Value != excludingPID,
                  bounds.width >= 100,
                  bounds.height >= 100 else {
                return nil
            }
            return NeutralGeometryWindow(
                id: CGWindowID(number.uint32Value),
                ownerPID: pid.int32Value,
                ownerName: owner,
                bounds: bounds
            )
        }
    }

    static func currentWindow(
        matching selected: NeutralGeometryWindow
    ) -> NeutralGeometryWindow? {
        visibleWindows().first {
            $0.id == selected.id && $0.ownerPID == selected.ownerPID
        }
    }

    static func isActive(_ selected: NeutralGeometryWindow) -> Bool {
        guard NSWorkspace.shared.frontmostApplication?.processIdentifier
                == selected.ownerPID,
              let firstForOwner = visibleWindows().first(where: {
                  $0.ownerPID == selected.ownerPID
              }) else {
            return false
        }
        return firstForOwner.id == selected.id
    }

    static func isTopmostAtPoint(
        _ selected: NeutralGeometryWindow,
        point: CGPoint
    ) -> Bool {
        guard selected.bounds.contains(point),
              let values = CGWindowListCopyWindowInfo(
                  [.optionOnScreenOnly, .excludeDesktopElements],
                  kCGNullWindowID
              ) as? [[String: Any]] else {
            return false
        }
        for value in values {
            guard let number = value[kCGWindowNumber as String] as? NSNumber,
                  let layer = value[kCGWindowLayer as String] as? NSNumber,
                  let boundsValue = value[kCGWindowBounds as String]
                    as? [String: Any],
                  let bounds = CGRect(
                      dictionaryRepresentation: boundsValue as CFDictionary
                  ),
                  layer.intValue >= 0,
                  bounds.contains(point) else {
                continue
            }
            return CGWindowID(number.uint32Value) == selected.id
        }
        return false
    }
}

@MainActor
final class NeutralGeometryCaptureSession: ObservableObject {
    @MainActor
    struct SystemInterface {
        let preflightListenAccess: () -> Bool
        let requestListenAccess: () -> Bool
        let visibleWindows: () -> [NeutralGeometryWindow]
        let currentWindow: (NeutralGeometryWindow) -> NeutralGeometryWindow?
        let isActive: (NeutralGeometryWindow) -> Bool
        let isTopmostAtPoint: (NeutralGeometryWindow, CGPoint) -> Bool
        let addGlobalMonitor:
            (NSEvent.EventTypeMask, @escaping (NSEvent) -> Void) -> Any?
        let removeMonitor: (Any) -> Void

        static let live = SystemInterface(
            preflightListenAccess: { CGPreflightListenEventAccess() },
            requestListenAccess: { CGRequestListenEventAccess() },
            visibleWindows: { NeutralGeometryWindowCatalog.visibleWindows() },
            currentWindow: { NeutralGeometryWindowCatalog.currentWindow(matching: $0) },
            isActive: { NeutralGeometryWindowCatalog.isActive($0) },
            isTopmostAtPoint: {
                NeutralGeometryWindowCatalog.isTopmostAtPoint($0, point: $1)
            },
            addGlobalMonitor: {
                NSEvent.addGlobalMonitorForEvents(matching: $0, handler: $1)
            },
            removeMonitor: { NSEvent.removeMonitor($0) }
        )
    }

    static let moduleID = "example.verbal-orders.relative-xy-recorder"
    static let bindingID = "verbal-orders.neutral.selected-window"
    static let maximumSessionEvents = 4_096
    static let moveCoalescingDistance = 0.0025

    @Published private(set) var mode: NeutralGeometryCaptureMode = .disarmed
    @Published private(set) var availableWindows: [NeutralGeometryWindow] = []
    @Published private(set) var selectedWindow: NeutralGeometryWindow?
    @Published private(set) var capturedEvents: [ConversationModuleEvent] = []
    @Published private(set) var deliveredEventCount = 0
    @Published private(set) var droppedEventCount = 0
    @Published private(set) var lastError: String?
    @Published private(set) var inputMonitoringAvailable = false

    private var monitor: Any?
    private var startNanoseconds: UInt64?
    private var nextEventOrdinal = 1
    private let system: SystemInterface

    var pendingEventCount: Int {
        max(0, capturedEvents.count - deliveredEventCount)
    }

    var canExport: Bool {
        mode == .review && !capturedEvents.isEmpty
    }

    init(system: SystemInterface = .live) {
        self.system = system
        refreshWindows()
        inputMonitoringAvailable = system.preflightListenAccess()
    }

    func refreshWindows() {
        availableWindows = system.visibleWindows()
        if let selectedWindow,
           let refreshed = availableWindows.first(where: {
               $0.id == selectedWindow.id && $0.ownerPID == selectedWindow.ownerPID
           }) {
            self.selectedWindow = refreshed
        } else if selectedWindow != nil {
            revoke(reason: NeutralGeometryCaptureError.windowChanged.localizedDescription)
        }
    }

    func select(windowID: CGWindowID) {
        guard let window = availableWindows.first(where: { $0.id == windowID }) else {
            lastError = NeutralGeometryCaptureError.noWindow.localizedDescription
            return
        }
        stopMonitor()
        capturedEvents = []
        deliveredEventCount = 0
        droppedEventCount = 0
        nextEventOrdinal = 1
        selectedWindow = window
        mode = .armed
        lastError = nil
    }

    func requestInputMonitoring() {
        inputMonitoringAvailable =
            system.preflightListenAccess() || system.requestListenAccess()
        if !inputMonitoringAvailable {
            lastError =
                NeutralGeometryCaptureError.inputMonitoringRequired.localizedDescription
        }
    }

    func setInputMonitoringToggle(_ enabled: Bool) {
        if enabled {
            requestInputMonitoring()
            return
        }

        // macOS does not let an app revoke its own Input Monitoring grant. Keep
        // the switch truthful and direct the user to the system permission pane.
        inputMonitoringAvailable = system.preflightListenAccess()
        if inputMonitoringAvailable {
            lastError =
                "To turn off Input Monitoring, remove Operations Floater in "
                    + "System Settings → Privacy & Security → Input Monitoring."
        }
    }

    func start() {
        guard selectedWindow != nil else {
            lastError = NeutralGeometryCaptureError.noWindow.localizedDescription
            return
        }
        inputMonitoringAvailable = system.preflightListenAccess()
        guard inputMonitoringAvailable else {
            lastError =
                NeutralGeometryCaptureError.inputMonitoringRequired.localizedDescription
            return
        }
        guard installMonitor() else {
            lastError =
                NeutralGeometryCaptureError.inputMonitoringRequired.localizedDescription
            return
        }
        startNanoseconds = DispatchTime.now().uptimeNanoseconds
        mode = .recording
        lastError = nil
    }

    func pause() {
        guard mode == .recording else { return }
        stopMonitor()
        mode = .paused
    }

    func resume() {
        guard mode == .paused else { return }
        start()
    }

    func stop() {
        guard mode == .recording || mode == .paused else { return }
        stopMonitor()
        mode = .review
    }

    func revoke(reason: String? = nil) {
        stopMonitor()
        mode = .disarmed
        selectedWindow = nil
        availableWindows = []
        capturedEvents = []
        deliveredEventCount = 0
        droppedEventCount = 0
        nextEventOrdinal = 1
        startNanoseconds = nil
        lastError = reason
    }

    func snapshot() throws -> NeutralGeometryCaptureSnapshot {
        guard let selected = selectedWindow,
              let current = system.currentWindow(selected) else {
            throw NeutralGeometryCaptureError.windowChanged
        }
        let pending = Array(capturedEvents.dropFirst(deliveredEventCount))
        let bounded = Array(pending.suffix(ConversationModuleContract.maximumEvents))
        return NeutralGeometryCaptureSnapshot(
            events: reindexed(bounded),
            window: ConversationModuleWindowContext(
                bindingID: Self.bindingID,
                width: min(8_192, max(100, Int(current.bounds.width.rounded()))),
                height: min(8_192, max(100, Int(current.bounds.height.rounded())))
            )
        )
    }

    func accept(
        _ snapshot: NeutralGeometryCaptureSnapshot,
        narration: String,
        commands: [RecorderNormalizedCommand] = [],
        response: ConversationModuleResponse
    ) {
        deliveredEventCount = capturedEvents.count
        let words = narration
            .lowercased()
            .split(whereSeparator: { !$0.isLetter })
            .map(String.init)
        let commandKinds = Set(commands.map(\.kind))
        if response.state == .completed
            || words == ["stop", "recording"]
            || commandKinds.contains(.stop) {
            stop()
        } else if words == ["pause", "recording"] || commandKinds.contains(.pause) {
            pause()
        } else if (words == ["resume", "recording"] || commandKinds.contains(.resume)),
                  mode == .paused {
            resume()
        }
        lastError = nil
    }

    func preserveAfterFailure(_ error: Error) {
        lastError = error.localizedDescription
    }

    func exportData(provenance: ConversationModuleProvenance) throws -> Data {
        guard mode == .review else {
            throw NeutralGeometryCaptureError.reviewRequired
        }
        guard let selectedWindow, !capturedEvents.isEmpty else {
            throw NeutralGeometryCaptureError.noEvents
        }
        do {
            try provenance.validate(
                expectedSourceID:
                    "example.project-verbal-orders.relative-xy-recorder"
            )
        } catch {
            throw NeutralGeometryCaptureError.invalidProvenance
        }
        let value = NeutralGeometryCaptureExport(
            schema: NeutralGeometryCaptureExport.schema,
            moduleID: Self.moduleID,
            windowBindingID: Self.bindingID,
            windowWidth: Int(selectedWindow.bounds.width.rounded()),
            windowHeight: Int(selectedWindow.bounds.height.rounded()),
            eventCount: capturedEvents.count,
            droppedEventCount: droppedEventCount,
            provenanceSourceID: provenance.sourceID,
            buildDigest: provenance.buildDigest,
            selectedWindowIdentityPersisted: false,
            charactersRecovered: false,
            screenCaptureUsed: false,
            ocrUsed: false,
            events: capturedEvents.enumerated().map { index, event in
                NeutralGeometryCaptureExport.Event(
                    ordinal: index + 1,
                    kind: event.kind,
                    pointerPhase: event.pointerPhase,
                    normalizedX: event.normalizedX,
                    normalizedY: event.normalizedY,
                    keyPhase: event.keyPhase,
                    keyCode: event.keyCode,
                    modifierFlags: event.modifierFlags,
                    buttonNumber: event.buttonNumber,
                    scrollDeltaX: event.scrollDeltaX,
                    scrollDeltaY: event.scrollDeltaY,
                    elapsedMilliseconds: event.elapsedMilliseconds
                )
            }
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        return try encoder.encode(value)
    }

    func ingestForTesting(_ raw: NeutralGeometryRawEvent) {
        ingest(raw)
    }

    static func makeEvent(
        from raw: NeutralGeometryRawEvent,
        bounds: CGRect,
        pointerIsTopmost: Bool,
        keyWindowIsActive: Bool,
        eventID: String = "event_input-test",
        elapsedMilliseconds: Int = 0
    ) -> ConversationModuleEvent? {
        switch raw.kind {
        case let .pointer(phase, button):
            guard pointerIsTopmost,
                  let location = raw.location,
                  let point = normalized(location, within: bounds) else {
                return nil
            }
            return ConversationModuleEvent(
                eventID: eventID,
                sequence: 1,
                kind: .normalizedPointer,
                pointerPhase: phase,
                normalizedX: point.x,
                normalizedY: point.y,
                buttonNumber: button,
                elapsedMilliseconds: elapsedMilliseconds
            )
        case let .scroll(deltaX, deltaY):
            guard pointerIsTopmost,
                  let location = raw.location,
                  let point = normalized(location, within: bounds) else {
                return nil
            }
            return ConversationModuleEvent(
                eventID: eventID,
                sequence: 1,
                kind: .scroll,
                normalizedX: point.x,
                normalizedY: point.y,
                scrollDeltaX: deltaX,
                scrollDeltaY: deltaY,
                elapsedMilliseconds: elapsedMilliseconds
            )
        case let .key(phase, code, modifiers):
            guard keyWindowIsActive else { return nil }
            return ConversationModuleEvent(
                eventID: eventID,
                sequence: 1,
                kind: .rawKeyboard,
                keyPhase: phase,
                keyCode: code,
                modifierFlags: modifiers,
                elapsedMilliseconds: elapsedMilliseconds
            )
        }
    }

    private func installMonitor() -> Bool {
        if monitor != nil { return true }
        let mask: NSEvent.EventTypeMask = [
            .mouseMoved,
            .leftMouseDown, .leftMouseUp,
            .rightMouseDown, .rightMouseUp,
            .otherMouseDown, .otherMouseUp,
            .leftMouseDragged, .rightMouseDragged, .otherMouseDragged,
            .scrollWheel,
            .keyDown, .keyUp, .flagsChanged,
        ]
        monitor = system.addGlobalMonitor(mask) {
            [weak self] event in
            let raw = Self.rawEvent(from: event)
            guard let raw else { return }
            DispatchQueue.main.async {
                self?.ingest(raw)
            }
        }
        return monitor != nil
    }

    private func stopMonitor() {
        if let monitor {
            system.removeMonitor(monitor)
            self.monitor = nil
        }
    }

    private static func rawEvent(from event: NSEvent) -> NeutralGeometryRawEvent? {
        let timestamp = DispatchTime.now().uptimeNanoseconds
        switch event.type {
        case .mouseMoved:
            return .init(
                kind: .pointer(.move, Int(event.buttonNumber)),
                location: event.cgEvent?.location,
                timestampNanoseconds: timestamp
            )
        case .leftMouseDown, .rightMouseDown, .otherMouseDown:
            return .init(
                kind: .pointer(.down, Int(event.buttonNumber)),
                location: event.cgEvent?.location,
                timestampNanoseconds: timestamp
            )
        case .leftMouseUp, .rightMouseUp, .otherMouseUp:
            return .init(
                kind: .pointer(.up, Int(event.buttonNumber)),
                location: event.cgEvent?.location,
                timestampNanoseconds: timestamp
            )
        case .leftMouseDragged, .rightMouseDragged, .otherMouseDragged:
            return .init(
                kind: .pointer(.drag, Int(event.buttonNumber)),
                location: event.cgEvent?.location,
                timestampNanoseconds: timestamp
            )
        case .scrollWheel:
            return .init(
                kind: .scroll(event.scrollingDeltaX, event.scrollingDeltaY),
                location: event.cgEvent?.location,
                timestampNanoseconds: timestamp
            )
        case .keyDown:
            return .init(
                kind: .key(
                    .down,
                    Int(event.keyCode),
                    UInt64(event.modifierFlags.rawValue)
                ),
                location: nil,
                timestampNanoseconds: timestamp
            )
        case .keyUp:
            return .init(
                kind: .key(
                    .up,
                    Int(event.keyCode),
                    UInt64(event.modifierFlags.rawValue)
                ),
                location: nil,
                timestampNanoseconds: timestamp
            )
        case .flagsChanged:
            return .init(
                kind: .key(
                    .flagsChanged,
                    Int(event.keyCode),
                    UInt64(event.modifierFlags.rawValue)
                ),
                location: nil,
                timestampNanoseconds: timestamp
            )
        default:
            return nil
        }
    }

    private func ingest(_ raw: NeutralGeometryRawEvent) {
        guard mode == .recording,
              let selected = selectedWindow,
              let current = system.currentWindow(selected) else {
            if mode == .recording {
                revoke(reason: NeutralGeometryCaptureError.windowChanged.localizedDescription)
            }
            return
        }
        selectedWindow = current
        let elapsed = elapsedMilliseconds(raw.timestampNanoseconds)
        let pointerAccepted = raw.location.map {
            system.isTopmostAtPoint(current, $0)
        } ?? false
        guard let event = Self.makeEvent(
            from: raw,
            bounds: current.bounds,
            pointerIsTopmost: pointerAccepted,
            keyWindowIsActive: system.isActive(current),
            eventID: nextEventID(),
            elapsedMilliseconds: elapsed
        ) else {
            droppedEventCount += 1
            return
        }
        append(event)
    }

    private func append(_ event: ConversationModuleEvent) {
        if event.kind == .normalizedPointer,
           event.pointerPhase == .move,
           let last = capturedEvents.last,
           last.kind == .normalizedPointer,
           last.pointerPhase == .move,
           let x = event.normalizedX,
           let y = event.normalizedY,
           let lastX = last.normalizedX,
           let lastY = last.normalizedY,
           hypot(x - lastX, y - lastY) < Self.moveCoalescingDistance {
            capturedEvents[capturedEvents.count - 1] = event
            return
        }
        capturedEvents.append(event)
        if capturedEvents.count > Self.maximumSessionEvents {
            let overflow = capturedEvents.count - Self.maximumSessionEvents
            capturedEvents.removeFirst(overflow)
            deliveredEventCount = max(0, deliveredEventCount - overflow)
            droppedEventCount += overflow
        }
    }

    private func nextEventID() -> String {
        defer { nextEventOrdinal += 1 }
        return "event_input-\(nextEventOrdinal)"
    }

    private func elapsedMilliseconds(_ now: UInt64) -> Int {
        guard let startNanoseconds else { return 0 }
        return min(
            86_400_000,
            Int((now >= startNanoseconds ? now - startNanoseconds : 0) / 1_000_000)
        )
    }

    private static func normalized(
        _ point: CGPoint,
        within bounds: CGRect
    ) -> CGPoint? {
        guard bounds.width > 0, bounds.height > 0 else { return nil }
        let x = (point.x - bounds.minX) / bounds.width
        let y = (point.y - bounds.minY) / bounds.height
        guard x.isFinite, y.isFinite, (0...1).contains(x), (0...1).contains(y) else {
            return nil
        }
        return CGPoint(x: x, y: y)
    }

    private func reindexed(
        _ events: [ConversationModuleEvent]
    ) -> [ConversationModuleEvent] {
        events.enumerated().map { index, event in
            ConversationModuleEvent(
                eventID: event.eventID,
                sequence: index + 1,
                kind: event.kind,
                pointerPhase: event.pointerPhase,
                normalizedX: event.normalizedX,
                normalizedY: event.normalizedY,
                navigationKey: event.navigationKey,
                keyPhase: event.keyPhase,
                keyCode: event.keyCode,
                modifierFlags: event.modifierFlags,
                buttonNumber: event.buttonNumber,
                scrollDeltaX: event.scrollDeltaX,
                scrollDeltaY: event.scrollDeltaY,
                elapsedMilliseconds: event.elapsedMilliseconds,
                placeholder: event.placeholder
            )
        }
    }
}

struct NeutralGeometryEventEcho: Identifiable, Equatable, Sendable {
    let id: String
    let elapsed: String
    let event: String
    let detail: String

    static func make(
        _ event: ConversationModuleEvent,
        ordinal: Int
    ) -> NeutralGeometryEventEcho {
        let elapsed = String(
            format: "+%.3fs",
            Double(event.elapsedMilliseconds ?? 0) / 1_000
        )
        switch event.kind {
        case .normalizedPointer:
            return .init(
                id: event.eventID,
                elapsed: elapsed,
                event: "Mouse \(event.pointerPhase?.rawValue ?? "event")",
                detail: String(
                    format: "x=%.3f, y=%.3f · button=%d",
                    event.normalizedX ?? 0,
                    event.normalizedY ?? 0,
                    event.buttonNumber ?? 0
                )
            )
        case .scroll:
            return .init(
                id: event.eventID,
                elapsed: elapsed,
                event: "Scroll",
                detail: String(
                    format: "x=%.3f, y=%.3f · Δx=%.1f, Δy=%.1f",
                    event.normalizedX ?? 0,
                    event.normalizedY ?? 0,
                    event.scrollDeltaX ?? 0,
                    event.scrollDeltaY ?? 0
                )
            )
        case .rawKeyboard:
            let keyCode = event.keyCode ?? -1
            return .init(
                id: event.eventID,
                elapsed: elapsed,
                event: "Key \(event.keyPhase?.rawValue ?? "event")",
                detail:
                    "\(keyLabel(keyCode)) · code=\(keyCode) · "
                    + String(format: "modifiers=0x%llx", event.modifierFlags ?? 0)
            )
        case .navigationKey:
            return .init(
                id: event.eventID,
                elapsed: elapsed,
                event: "Navigation key",
                detail: event.navigationKey?.rawValue ?? "unknown"
            )
        case .placeholder:
            return .init(
                id: event.eventID,
                elapsed: elapsed,
                event: "Excluded",
                detail: "Placeholder events are not accepted by this recorder."
            )
        }
    }

    private static func keyLabel(_ keyCode: Int) -> String {
        switch keyCode {
        case 36: "Return"
        case 48: "Tab"
        case 49: "Space"
        case 51: "Delete"
        case 53: "Escape"
        case 123: "Left arrow"
        case 124: "Right arrow"
        case 125: "Down arrow"
        case 126: "Up arrow"
        default: "Printable/non-navigation key"
        }
    }
}

struct NeutralGeometryCapturePanel: View {
    @ObservedObject var capture: NeutralGeometryCaptureSession
    let provenance: ConversationModuleProvenance?

    @State private var selectedID: CGWindowID?
    @State private var exportStatus: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("SELECTED-WINDOW INPUT")
                    .font(.system(size: 8, weight: .bold))
                Text(capture.mode.displayName)
                    .font(.system(size: 8, weight: .bold))
                    .foregroundStyle(capture.mode == .recording ? .green : .secondary)
                Spacer()
                Text(
                    "\(capture.capturedEvents.count) events · "
                        + "\(capture.pendingEventCount) pending"
                )
                .font(.system(size: 8).monospacedDigit())
                .foregroundStyle(.secondary)
            }

            HStack {
                Picker(
                    "Window",
                    selection: Binding(
                        get: { capture.selectedWindow?.id ?? selectedID },
                        set: { value in
                            selectedID = value
                            if let value { capture.select(windowID: value) }
                        }
                    )
                ) {
                    Text("Choose any visible window").tag(nil as CGWindowID?)
                    ForEach(capture.availableWindows) { window in
                        Text(window.displayName).tag(window.id as CGWindowID?)
                    }
                }
                .labelsHidden()
                .controlSize(.mini)

                Button("Refresh") {
                    capture.refreshWindows()
                }
                .controlSize(.mini)
            }

            HStack {
                switch capture.mode {
                case .disarmed, .armed:
                    Button("Start recording") { capture.start() }
                        .controlSize(.mini)
                        .disabled(capture.selectedWindow == nil)
                case .recording:
                    Button("Pause") { capture.pause() }
                        .controlSize(.mini)
                    Button("Stop & review") { capture.stop() }
                        .controlSize(.mini)
                case .paused:
                    Button("Resume") { capture.resume() }
                        .controlSize(.mini)
                    Button("Stop & review") { capture.stop() }
                        .controlSize(.mini)
                case .review:
                    Button("Export reviewed JSON") { export() }
                        .controlSize(.mini)
                        .disabled(!capture.canExport || provenance == nil)
                    Button("New session") {
                        capture.refreshWindows()
                        selectedID = nil
                        capture.revoke()
                        capture.refreshWindows()
                    }
                    .controlSize(.mini)
                }
                Toggle(
                    "Input monitoring",
                    isOn: Binding(
                        get: { capture.inputMonitoringAvailable },
                        set: { capture.setInputMonitoringToggle($0) }
                    )
                )
                .toggleStyle(.switch)
                .controlSize(.mini)
                .help(
                    capture.inputMonitoringAvailable
                        ? "Input Monitoring is enabled for this app."
                        : "Turn on to request macOS Input Monitoring permission."
                )
            }

            Text(
                "Captures all mouse, scroll, and key-code events only while this "
                    + "single selected window is active. Characters, titles, pixels, "
                    + "OCR, URLs, and window identity are never recorded."
            )
            .font(.system(size: 9))
            .foregroundStyle(.secondary)

            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text("CAPTURED EVENTS")
                        .font(.system(size: 8, weight: .bold))
                    Spacer()
                    Text(
                        "\(capture.capturedEvents.count) captured · "
                            + "\(capture.deliveredEventCount) accepted · "
                            + "\(capture.droppedEventCount) excluded"
                    )
                    .font(.system(size: 8).monospacedDigit())
                    .foregroundStyle(.secondary)
                }
                if capture.capturedEvents.isEmpty {
                    Text("No input events captured yet.")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(
                        Array(capture.capturedEvents.suffix(10).enumerated()),
                        id: \.element.eventID
                    ) { offset, event in
                        let ordinal =
                            max(0, capture.capturedEvents.count - 10) + offset + 1
                        let echo = NeutralGeometryEventEcho.make(
                            event,
                            ordinal: ordinal
                        )
                        HStack(alignment: .firstTextBaseline, spacing: 7) {
                            Text(echo.elapsed)
                                .frame(width: 48, alignment: .trailing)
                            Text(echo.event)
                                .frame(width: 78, alignment: .leading)
                            Text(echo.detail)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .font(.system(size: 9).monospacedDigit())
                        .foregroundStyle(.secondary)
                        .accessibilityElement(children: .combine)
                        .accessibilityLabel(
                            "Event \(ordinal), \(echo.elapsed), "
                                + "\(echo.event), \(echo.detail)"
                        )
                    }
                }
                Text("Replay disabled · printable characters are not reconstructed")
                    .font(.system(size: 8, weight: .medium))
                    .foregroundStyle(.orange)
            }
            .padding(6)
            .background(.quinary, in: RoundedRectangle(cornerRadius: 6))

            if let error = capture.lastError {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption2)
                    .foregroundStyle(.orange)
            }
            if let exportStatus {
                Text(exportStatus)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(7)
        .background(.background.opacity(0.55), in: RoundedRectangle(cornerRadius: 8))
    }

    private func export() {
        guard let provenance else {
            exportStatus = NeutralGeometryCaptureError.invalidProvenance.localizedDescription
            return
        }
        do {
            let data = try capture.exportData(provenance: provenance)
            let panel = NSSavePanel()
            panel.title = "Export Reviewed Relative XY Training"
            panel.nameFieldStringValue = "relative-xy-training.json"
            panel.allowedContentTypes = [.json]
            guard panel.runModal() == .OK, let url = panel.url else { return }
            try data.write(to: url, options: .atomic)
            exportStatus = "Reviewed artifact exported."
        } catch {
            exportStatus = error.localizedDescription
        }
    }
}
