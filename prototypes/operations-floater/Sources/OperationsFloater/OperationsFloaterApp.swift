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
    static let frameAutosaveName = "OperationsDashboardWindowDenseV1"

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
            contentRect: NSRect(
                origin: .zero,
                size: DashboardLayoutMetrics.defaultWindowSize
            ),
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
        panel.setFrameAutosaveName(Self.frameAutosaveName)
        panel.level = state.pinned ? .floating : .normal
        panel.minSize = DashboardLayoutMetrics.minimumWindowSize
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

private struct QueueLaneDefinition: Identifiable {
    let state: QueueRecord.State
    let title: String

    var id: QueueRecord.State { state }
}

private struct DashboardView: View {
    @StateObject private var state: DashboardState

    init(state: DashboardState) {
        _state = StateObject(wrappedValue: state)
    }

    var body: some View {
        GeometryReader { geometry in
            let metrics = DashboardLayoutMetrics(width: geometry.size.width)
            VStack(spacing: 0) {
                header
                Divider()
                ScrollView {
                    VStack(alignment: .leading, spacing: metrics.sectionSpacing) {
                        guideStrip(metrics: metrics)
                        resourceBudgetPanel(metrics: metrics)
                        queueGrid(metrics: metrics)
                        supportingGrid(metrics: metrics)
                    }
                    .padding(metrics.contentPadding)
                }
            }
        }
        .frame(
            minWidth: DashboardLayoutMetrics.minimumWindowSize.width,
            minHeight: DashboardLayoutMetrics.minimumWindowSize.height
        )
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
        .padding(.horizontal, 14)
        .padding(.vertical, 11)
    }

    private func guideStrip(metrics: DashboardLayoutMetrics) -> some View {
        let cue = state.snapshot.guideCue
        return VStack(alignment: .leading, spacing: 9) {
            HStack(spacing: 12) {
                AnimatedGuideAvatar(cue: cue)
                    .frame(width: metrics.guideSize, height: metrics.guideSize)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 3) {
                    Text(cue.title)
                        .font(.headline)
                    Text(cue.detail)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text("Local procedural guide")
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(guideAccent(for: cue.activity))
                }
                Spacer(minLength: 0)
            }

            LazyVGrid(
                columns: Array(
                    repeating: GridItem(.flexible(minimum: 52), spacing: 7),
                    count: 4
                ),
                spacing: 7
            ) {
                compactMetric(state.itemCount(for: .running), "running", .blue)
                compactMetric(state.itemCount(for: .queued), "queued", .orange)
                compactMetric(state.itemCount(for: .waiting), "waiting", .purple)
                compactMetric(state.itemCount(for: .ready), "ready", .green)
            }
        }
        .padding(11)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 14))
        .overlay(
            RoundedRectangle(cornerRadius: 14)
                .stroke(guideAccent(for: cue.activity).opacity(0.22), lineWidth: 1)
        )
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Queue guide: \(cue.title). \(cue.detail)")
    }

    private func compactMetric(_ count: Int, _ label: String, _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(String(count))
                .font(.headline.monospacedDigit())
                .foregroundStyle(color)
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .background(color.opacity(0.11), in: RoundedRectangle(cornerRadius: 8))
    }

    private func resourceBudgetPanel(metrics: DashboardLayoutMetrics) -> some View {
        dashboardPanel(
            title: "Resource budget",
            subtitle: "Scheduling evidence",
            metrics: metrics
        ) {
            LazyVGrid(
                columns: gridColumns(metrics: metrics),
                alignment: .leading,
                spacing: 0
            ) {
                ForEach(state.snapshot.resourceBudget) { record in
                    recordRow(
                        title: record.title,
                        detail: record.detail,
                        status: record.displayValue,
                        verification: record.verification.rawValue,
                        metrics: metrics
                    )
                }
            }
        }
    }

    private func queueGrid(metrics: DashboardLayoutMetrics) -> some View {
        let definitions = [
            QueueLaneDefinition(state: .running, title: "Running"),
            QueueLaneDefinition(state: .queued, title: "Queued"),
            QueueLaneDefinition(state: .waiting, title: "Waiting"),
            QueueLaneDefinition(state: .ready, title: "Ready")
        ].filter { definition in
            state.snapshot.queue.contains { $0.state == definition.state }
        }

        return LazyVGrid(
            columns: gridColumns(metrics: metrics),
            alignment: .leading,
            spacing: metrics.sectionSpacing
        ) {
            ForEach(definitions) { definition in
                let records = state.snapshot.queue.filter { $0.state == definition.state }
                dashboardPanel(
                    title: definition.title,
                    subtitle: "\(records.count) records",
                    metrics: metrics
                ) {
                    VStack(spacing: 0) {
                        ForEach(records) { record in
                            recordRow(
                                title: record.title,
                                detail: record.detail,
                                status: nil,
                                verification: record.verification.rawValue,
                                metrics: metrics
                            )
                        }
                    }
                }
            }
        }
    }

    private func supportingGrid(metrics: DashboardLayoutMetrics) -> some View {
        LazyVGrid(
            columns: gridColumns(metrics: metrics),
            alignment: .leading,
            spacing: metrics.sectionSpacing
        ) {
            dashboardPanel(
                title: "Tests and quality",
                subtitle: "\(state.snapshot.tests.count) records",
                metrics: metrics
            ) {
                VStack(spacing: 0) {
                    ForEach(state.snapshot.tests) { record in
                        recordRow(
                            title: record.title,
                            detail: record.detail,
                            status: record.result.rawValue,
                            verification: record.verification.rawValue,
                            metrics: metrics
                        )
                    }
                }
            }

            dashboardPanel(
                title: "Signals",
                subtitle: "\(state.snapshot.signals.count) records",
                metrics: metrics
            ) {
                VStack(spacing: 0) {
                    ForEach(state.snapshot.signals) { record in
                        recordRow(
                            title: record.title,
                            detail: record.detail,
                            status: record.state.rawValue,
                            verification: record.verification.rawValue,
                            metrics: metrics
                        )
                    }
                }
            }
        }
    }

    private func gridColumns(metrics: DashboardLayoutMetrics) -> [GridItem] {
        Array(
            repeating: GridItem(
                .flexible(minimum: 170),
                spacing: metrics.sectionSpacing,
                alignment: .top
            ),
            count: metrics.columnCount
        )
    }

    private func dashboardPanel<Content: View>(
        title: String,
        subtitle: String,
        metrics: DashboardLayoutMetrics,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(title.uppercased())
                    .font(.caption2.weight(.bold))
                    .foregroundStyle(.secondary)
                Spacer(minLength: 0)
                Text(subtitle)
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
            .padding(.horizontal, metrics.recordPadding)
            .padding(.vertical, 7)
            Divider()
            content()
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .background(.quaternary, in: RoundedRectangle(cornerRadius: 11))
        .clipShape(RoundedRectangle(cornerRadius: 11))
    }

    private func recordRow(
        title: String,
        detail: String,
        status: String?,
        verification: String,
        metrics: DashboardLayoutMetrics
    ) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(title)
                    .font(.caption.weight(.semibold))
                    .lineLimit(2)
                Spacer(minLength: 4)
                if let status {
                    compactBadge(status)
                }
            }
            Text(detail)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .lineLimit(metrics.density == .dense ? 2 : 3)
            compactBadge(verification)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(metrics.recordPadding)
        .overlay(alignment: .bottom) {
            Divider()
        }
    }

    private func compactBadge(_ value: String) -> some View {
        Text(value.replacingOccurrences(of: "-", with: " "))
            .font(.system(size: 9, weight: .semibold))
            .foregroundStyle(.secondary)
            .padding(.horizontal, 5)
            .padding(.vertical, 2)
            .background(.quinary, in: Capsule())
    }

    private func guideAccent(for activity: GuideActivity) -> Color {
        switch activity {
        case .attention:
            .orange
        case .active:
            .cyan
        case .ready:
            .green
        case .waiting:
            .purple
        case .idle:
            .secondary
        }
    }

}

/// A procedural, non-personal avatar. No image asset, camera, microphone, or
/// network service is used; the motion is generated locally by TimelineView.
private struct AnimatedGuideAvatar: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    let cue: GuideCue

    var body: some View {
        TimelineView(
            .animation(
                minimumInterval: reduceMotion ? 1.0 : 1.0 / 30.0,
                paused: reduceMotion
            )
        ) { timeline in
            let time = timeline.date.timeIntervalSinceReferenceDate
            let frame = GuideMotionSampler.frame(
                at: time,
                activity: cue.activity,
                reduceMotion: reduceMotion
            )

            ZStack {
                Circle()
                    .fill(
                        AngularGradient(
                            colors: [.indigo, accent, .mint, .indigo],
                            center: .center
                        )
                    )
                    .opacity(0.23)
                    .scaleEffect(frame.pulse)
                Circle()
                    .fill(.ultraThinMaterial)
                    .overlay(Circle().stroke(.white.opacity(0.38), lineWidth: 1))
                    .padding(7)

                Circle()
                    .fill(accent.gradient)
                    .frame(width: 54, height: 54)
                    .offset(y: frame.bob)
                Circle()
                    .fill(accent.opacity(0.85))
                    .frame(width: 17, height: 17)
                    .offset(x: -27, y: frame.bob + 4)
                Circle()
                    .fill(accent.opacity(0.85))
                    .frame(width: 17, height: 17)
                    .offset(x: 27, y: frame.bob + 4)

                HStack(spacing: 13) {
                    Capsule().fill(.white).frame(width: 7, height: 10 * frame.eyeScale)
                    Capsule().fill(.white).frame(width: 7, height: 10 * frame.eyeScale)
                }
                .offset(y: frame.bob - 5)
                Capsule()
                    .fill(.white.opacity(0.9))
                    .frame(width: 18, height: 4)
                    .offset(y: frame.bob + 13)
                Capsule()
                    .fill(accent.opacity(0.9))
                    .frame(width: 10, height: 29)
                    .rotationEffect(.degrees(-35 + frame.wave))
                    .offset(x: 31, y: frame.bob + 29)
            }
            .drawingGroup()
        }
    }

    private var accent: Color {
        switch cue.activity {
        case .attention:
            .orange
        case .active:
            .cyan
        case .ready:
            .green
        case .waiting:
            .purple
        case .idle:
            .indigo
        }
    }
}
