// The executable entry point is intentionally not named main.swift: SwiftPM
// reserves that filename for top-level program code, which conflicts with @main.
import AppKit
import SwiftUI
import UniformTypeIdentifiers

@main
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private static let shared = AppDelegate()
    private let dashboardState = DashboardState()
    private lazy var windowController = DashboardWindowController(state: dashboardState)

    static func main() {
        let application = NSApplication.shared
        application.delegate = shared
        application.setActivationPolicy(.regular)
        application.run()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        configureMainMenu()
        showDashboard(nil)
    }

    func applicationShouldHandleReopen(
        _ sender: NSApplication,
        hasVisibleWindows flag: Bool
    ) -> Bool {
        showDashboard(nil)
        return true
    }

    @objc private func showDashboard(_ sender: Any?) {
        windowController.show(sender)
    }

    @objc private func closeDashboard(_ sender: Any?) {
        windowController.close(sender)
    }

    @objc private func importLocalSnapshot(_ sender: Any?) {
        let picker = NSOpenPanel()
        picker.title = "Import Local Operations Snapshot"
        picker.message = "Choose a canonical local snapshot. Its source path is not retained."
        picker.allowedContentTypes = [.json]
        picker.allowsMultipleSelection = false
        picker.canChooseDirectories = false
        picker.canChooseFiles = true

        guard picker.runModal() == .OK, let sourceURL = picker.url else { return }
        do {
            try dashboardState.importLocalSnapshot(from: sourceURL)
            showDashboard(sender)
        } catch {
            showAdapterError(
                title: "Snapshot Not Imported",
                message: error.localizedDescription
            )
        }
    }

    @objc private func restorePreviousSnapshot(_ sender: Any?) {
        do {
            try dashboardState.restorePreviousSnapshot()
            showDashboard(sender)
        } catch {
            showAdapterError(
                title: "Snapshot Not Restored",
                message: error.localizedDescription
            )
        }
    }

    private func showAdapterError(title: String, message: String) {
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = title
        alert.informativeText = message
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    private func configureMainMenu() {
        let mainMenu = NSMenu()
        let applicationMenuItem = NSMenuItem()
        let applicationMenu = NSMenu()

        let aboutItem = applicationMenu.addItem(
            withTitle: "About Operations Floater",
            action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)),
            keyEquivalent: ""
        )
        aboutItem.target = NSApplication.shared
        applicationMenu.addItem(.separator())

        let showItem = applicationMenu.addItem(
            withTitle: "Show Dashboard",
            action: #selector(showDashboard(_:)),
            keyEquivalent: "0"
        )
        showItem.target = self
        applicationMenu.addItem(.separator())

        let importItem = applicationMenu.addItem(
            withTitle: "Import Local Snapshot…",
            action: #selector(importLocalSnapshot(_:)),
            keyEquivalent: "i"
        )
        importItem.target = self
        let restoreItem = applicationMenu.addItem(
            withTitle: "Restore Previous Snapshot",
            action: #selector(restorePreviousSnapshot(_:)),
            keyEquivalent: ""
        )
        restoreItem.target = self
        applicationMenu.addItem(.separator())

        let quitItem = applicationMenu.addItem(
            withTitle: "Quit Operations Floater",
            action: #selector(NSApplication.terminate(_:)),
            keyEquivalent: "q"
        )
        quitItem.target = NSApplication.shared

        applicationMenuItem.submenu = applicationMenu
        mainMenu.addItem(applicationMenuItem)

        let windowMenuItem = NSMenuItem()
        let windowMenu = NSMenu(title: "Window")
        let closeWindowItem = windowMenu.addItem(
            withTitle: "Close Window",
            action: #selector(closeDashboard(_:)),
            keyEquivalent: "w"
        )
        closeWindowItem.target = self
        windowMenu.addItem(.separator())
        let showWindowItem = windowMenu.addItem(
            withTitle: "Show Dashboard",
            action: #selector(showDashboard(_:)),
            keyEquivalent: "0"
        )
        showWindowItem.target = self
        windowMenuItem.submenu = windowMenu
        mainMenu.addItem(windowMenuItem)

        NSApplication.shared.mainMenu = mainMenu
        NSApplication.shared.windowsMenu = windowMenu
    }
}

@MainActor
final class DashboardWindowController {
    private(set) var panel: NSWindow?
    private let state: DashboardState
    private let activatesApplication: Bool

    init(state: DashboardState, activatesApplication: Bool = true) {
        self.state = state
        self.activatesApplication = activatesApplication
    }

    @discardableResult
    func show(_ sender: Any? = nil) -> NSWindow {
        let panel = panel ?? makeDashboardWindow()
        panel.level = state.pinned ? .floating : .normal
        panel.makeKeyAndOrderFront(sender)
        panel.orderFrontRegardless()
        if activatesApplication {
            NSApplication.shared.activate(ignoringOtherApps: true)
        }
        return panel
    }

    func close(_ sender: Any? = nil) {
        panel?.performClose(sender)
    }

    private func makeDashboardWindow() -> NSWindow {
        let panel = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 420, height: 680),
            styleMask: [.titled, .closable, .resizable, .utilityWindow, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        panel.title = "Operations dashboard"
        panel.titleVisibility = .hidden
        panel.isMovableByWindowBackground = true
        panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.tabbingMode = .disallowed
        panel.setFrameAutosaveName("OperationsDashboardWindow")
        panel.level = state.pinned ? .floating : .normal
        panel.minSize = NSSize(width: 340, height: 440)
        panel.center()
        panel.contentView = NSHostingView(rootView: DashboardView(state: state))
        state.onPinnedChange = { [weak panel] isPinned in
            panel?.level = isPinned ? .floating : .normal
        }
        self.panel = panel
        return panel
    }
}

@MainActor
final class DashboardState: ObservableObject {
    @Published var pinned = true { didSet { onPinnedChange?(pinned) } }
    @Published private(set) var snapshot: DashboardSnapshot
    @Published private(set) var sourceDescription: String
    @Published private(set) var canRestorePreviousSnapshot: Bool
    var onPinnedChange: ((Bool) -> Void)?

    private static let defaultSnapshotURL: URL = {
        let applicationSupport = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first!
        return applicationSupport
            .appendingPathComponent("OperationsFloater", isDirectory: true)
            .appendingPathComponent("dashboard-state.json")
    }()
    private let store: LocalSnapshotStore

    init(snapshotURL: URL? = nil) {
        store = LocalSnapshotStore(snapshotURL: snapshotURL ?? Self.defaultSnapshotURL)
        snapshot = .sample
        sourceDescription = "Generic sample — local only"
        canRestorePreviousSnapshot = false
        reload()
    }

    func reload() {
        guard let decoded = store.load() else {
            snapshot = .sample
            sourceDescription = "Generic sample — local only"
            canRestorePreviousSnapshot = store.hasValidPreviousSnapshot()
            return
        }
        use(decoded)
    }

    func importLocalSnapshot(from sourceURL: URL) throws {
        use(try store.importLocalSnapshot(from: sourceURL))
    }

    func restorePreviousSnapshot() throws {
        use(try store.restorePreviousSnapshot())
    }

    func itemCount(for stateToCount: QueueRecord.State) -> Int {
        snapshot.queue.lazy.filter { $0.state == stateToCount }.count
    }

    private func use(_ decoded: DashboardSnapshot) {
        snapshot = decoded
        sourceDescription =
            decoded.mode == .local
            ? "Locally verified snapshot — refreshes automatically"
            : "Sanitized snapshot — refreshes automatically"
        canRestorePreviousSnapshot = store.hasValidPreviousSnapshot()
    }
}

private struct DashboardView: View {
    @StateObject private var state: DashboardState

    init(state: DashboardState) {
        _state = StateObject(wrappedValue: state)
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    avatar
                    queueSummary
                    queueLane(title: "Running", queueState: .running)
                    queueLane(title: "Queued", queueState: .queued)
                    queueLane(title: "Waiting", queueState: .waiting)
                    queueLane(title: "Ready", queueState: .ready)
                    testSection
                    resourceSection
                    signalSection
                }
                .padding(18)
            }
        }
        .frame(minWidth: 340, minHeight: 440)
        .background(.regularMaterial)
        .onReceive(Timer.publish(every: 2, on: .main, in: .common).autoconnect()) { _ in
            state.reload()
        }
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("Operations dashboard").font(.headline)
                Text(state.sourceDescription)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Toggle("Keep in front", isOn: $state.pinned)
                .toggleStyle(.switch)
                .controlSize(.small)
                .accessibilityLabel("Keep dashboard in front")
        }
        .padding(16)
    }

    private var avatar: some View {
        HStack(spacing: 14) {
            AnimatedGuideAvatar()
                .frame(width: 92, height: 92)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 6) {
                Text("Queue guide").font(.headline)
                Text(
                    state.snapshot.queue.contains(where: { $0.state == .running })
                    ? "Tracking the active lane."
                    : "The active lane is clear."
                )
                .font(.subheadline)
                .foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
        .padding(14)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 16))
    }

    private var queueSummary: some View {
        HStack(spacing: 10) {
            metric(count(for: .running), "running", .blue)
            metric(count(for: .queued), "queued", .orange)
            metric(count(for: .waiting), "waiting", .purple)
        }
    }

    private func count(for stateToCount: QueueRecord.State) -> String {
        String(state.itemCount(for: stateToCount))
    }

    private func metric(_ number: String, _ label: String, _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(number).font(.title2.bold()).foregroundStyle(color)
            Text(label).font(.caption).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(color.opacity(0.12), in: RoundedRectangle(cornerRadius: 10))
    }

    @ViewBuilder
    private func queueLane(title: String, queueState: QueueRecord.State) -> some View {
        let selected = state.snapshot.queue.filter { $0.state == queueState }
        if !selected.isEmpty {
            recordSection(title: title, records: selected) { record in
                recordCard(
                    title: record.title,
                    detail: record.detail,
                    badge: record.verification.rawValue
                )
            }
        }
    }

    private var testSection: some View {
        recordSection(title: "Tests", records: state.snapshot.tests) { record in
            recordCard(title: record.title, detail: record.detail, badge: record.result.rawValue)
        }
    }

    private var resourceSection: some View {
        recordSection(title: "Resource budget", records: state.snapshot.resourceBudget) { record in
            recordCard(title: record.title, detail: record.detail, badge: record.displayValue)
        }
    }

    private var signalSection: some View {
        recordSection(title: "Signals", records: state.snapshot.signals) { record in
            recordCard(title: record.title, detail: record.detail, badge: record.state.rawValue)
        }
    }

    private func recordSection<Record: Identifiable, Content: View>(
        title: String,
        records: [Record],
        @ViewBuilder content: @escaping (Record) -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title.uppercased())
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
            ForEach(records) { record in
                content(record)
            }
        }
    }

    private func recordCard(title: String, detail: String, badge: String) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .firstTextBaseline) {
                Text(title).font(.body.weight(.medium))
                Spacer()
                Text(badge.replacingOccurrences(of: "-", with: " "))
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.secondary)
            }
            Text(detail).font(.caption).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(.quaternary, in: RoundedRectangle(cornerRadius: 10))
    }
}

/// A procedural, non-personal avatar. No image asset, camera, microphone, or
/// network service is used; the motion is generated locally by TimelineView.
private struct AnimatedGuideAvatar: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        TimelineView(
            .animation(
                minimumInterval: reduceMotion ? 1.0 : 1.0 / 30.0,
                paused: reduceMotion
            )
        ) { timeline in
            let time = timeline.date.timeIntervalSinceReferenceDate
            let bob = reduceMotion ? 0 : sin(time * 2.0) * 3.0
            let blink = reduceMotion ? 1.0 : (abs(sin(time * 0.72)) > 0.985 ? 0.12 : 1.0)
            let wave = reduceMotion ? 0 : sin(time * 2.0) * 12.0
            let pulse = reduceMotion ? 1.0 : 1.0 + sin(time * 1.6) * 0.035

            ZStack {
                Circle()
                    .fill(
                        AngularGradient(
                            colors: [.indigo, .cyan, .mint, .indigo],
                            center: .center
                        )
                    )
                    .opacity(0.23)
                    .scaleEffect(pulse)
                Circle()
                    .fill(.ultraThinMaterial)
                    .overlay(Circle().stroke(.white.opacity(0.38), lineWidth: 1))
                    .padding(7)

                Circle()
                    .fill(Color.indigo.opacity(0.95))
                    .frame(width: 54, height: 54)
                    .offset(y: bob)
                Circle()
                    .fill(Color.indigo.opacity(0.85))
                    .frame(width: 17, height: 17)
                    .offset(x: -27, y: bob + 4)
                Circle()
                    .fill(Color.indigo.opacity(0.85))
                    .frame(width: 17, height: 17)
                    .offset(x: 27, y: bob + 4)

                HStack(spacing: 13) {
                    Capsule().fill(.white).frame(width: 7, height: 10 * blink)
                    Capsule().fill(.white).frame(width: 7, height: 10 * blink)
                }
                .offset(y: bob - 5)
                Capsule()
                    .fill(.white.opacity(0.9))
                    .frame(width: 18, height: 4)
                    .offset(y: bob + 13)
                Capsule()
                    .fill(Color.cyan.opacity(0.9))
                    .frame(width: 10, height: 29)
                    .rotationEffect(.degrees(-35 + wave))
                    .offset(x: 31, y: bob + 29)
            }
            .drawingGroup()
        }
    }
}
