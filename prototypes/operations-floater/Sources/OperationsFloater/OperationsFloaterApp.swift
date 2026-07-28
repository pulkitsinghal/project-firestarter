// The executable entry point is intentionally not named main.swift: SwiftPM
// reserves that filename for top-level program code, which conflicts with @main.
import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct DashboardLaunchConfiguration: Equatable {
    static let backgroundUITestArgument = "--background-ui-test"
    static let syntheticConversationUITestArgument =
        "--synthetic-conversation-ui-test"
    static let geometryConversationUITestArgument =
        "--geometry-conversation-ui-test"
    static let recorderNormalizerUITestArgument =
        "--recorder-normalizer-ui-test"
    static let compactUITestArgument = "--compact-ui-test"

    let isBackgroundUITest: Bool
    let usesSyntheticConversationFixture: Bool
    let usesGeometryConversationFixture: Bool
    let usesRecorderNormalizerFixture: Bool
    let usesCompactTestFrame: Bool

    init(arguments: [String] = ProcessInfo.processInfo.arguments) {
        isBackgroundUITest = arguments.contains(Self.backgroundUITestArgument)
        usesSyntheticConversationFixture =
            isBackgroundUITest
            && arguments.contains(Self.syntheticConversationUITestArgument)
        usesGeometryConversationFixture =
            isBackgroundUITest
            && arguments.contains(Self.geometryConversationUITestArgument)
        usesRecorderNormalizerFixture =
            isBackgroundUITest
            && arguments.contains(Self.recorderNormalizerUITestArgument)
        usesCompactTestFrame =
            isBackgroundUITest
            && arguments.contains(Self.compactUITestArgument)
    }

    var initialPinned: Bool { false }
    var activatesApplication: Bool { !isBackgroundUITest }
    var foregroundsWindow: Bool { !isBackgroundUITest }
    var joinsAllSpaces: Bool { false }
    var usesSavedFrame: Bool { !isBackgroundUITest }
    var initialWindowSize: CGSize {
        usesCompactTestFrame
            ? DashboardLayoutMetrics.minimumWindowSize
            : DashboardLayoutMetrics.defaultWindowSize
    }
    var conversationFixtureModuleID: String? {
        if usesRecorderNormalizerFixture {
            return ConversationModuleAllowlist.relativeXYRecorderManifest.moduleID
        }
        if usesGeometryConversationFixture {
            return ConversationModuleAllowlist.geometryRecorderManifest.moduleID
        }
        if usesSyntheticConversationFixture {
            return ConversationModuleAllowlist.syntheticManifest.moduleID
        }
        return nil
    }
}

@main
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private static let shared = AppDelegate()
    private let launchConfiguration: DashboardLaunchConfiguration
    private let dashboardState: DashboardState
    private lazy var windowController = DashboardWindowController(
        state: dashboardState,
        activatesApplication: launchConfiguration.activatesApplication,
        foregroundsWindow: launchConfiguration.foregroundsWindow,
        joinsAllSpaces: launchConfiguration.joinsAllSpaces,
        usesSavedFrame: launchConfiguration.usesSavedFrame,
        initialWindowSize: launchConfiguration.initialWindowSize,
        conversationFixtureModuleID:
            launchConfiguration.conversationFixtureModuleID,
        conversationFixtureUsesRecorderNormalizer:
            launchConfiguration.usesRecorderNormalizerFixture
    )

    private override init() {
        let launchConfiguration = DashboardLaunchConfiguration()
        self.launchConfiguration = launchConfiguration
        dashboardState = DashboardState(initialPinned: launchConfiguration.initialPinned)
        super.init()
    }

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

    static func collectionBehavior(joinsAllSpaces: Bool) -> NSWindow.CollectionBehavior {
        joinsAllSpaces
            ? [.canJoinAllSpaces, .fullScreenAuxiliary]
            : [.managed]
    }

    private(set) var panel: NSWindow?
    private let state: DashboardState
    private let activatesApplication: Bool
    private let foregroundsWindow: Bool
    private let joinsAllSpaces: Bool
    private let usesSavedFrame: Bool
    private let initialWindowSize: CGSize
    private let conversationFixtureModuleID: String?
    private let conversationFixtureUsesRecorderNormalizer: Bool

    init(
        state: DashboardState,
        activatesApplication: Bool = true,
        foregroundsWindow: Bool = true,
        joinsAllSpaces: Bool = false,
        usesSavedFrame: Bool = true,
        initialWindowSize: CGSize = DashboardLayoutMetrics.defaultWindowSize,
        conversationFixtureModuleID: String? = nil,
        conversationFixtureUsesRecorderNormalizer: Bool = false
    ) {
        self.state = state
        self.activatesApplication = activatesApplication
        self.foregroundsWindow = foregroundsWindow
        self.joinsAllSpaces = joinsAllSpaces
        self.usesSavedFrame = usesSavedFrame
        self.initialWindowSize = initialWindowSize
        self.conversationFixtureModuleID = conversationFixtureModuleID
        self.conversationFixtureUsesRecorderNormalizer =
            conversationFixtureUsesRecorderNormalizer
    }

    @discardableResult
    func show(_ sender: Any? = nil) -> NSWindow {
        let panel = panel ?? makeDashboardWindow()
        panel.level = state.pinned ? .floating : .normal
        if foregroundsWindow {
            panel.makeKeyAndOrderFront(sender)
            panel.orderFrontRegardless()
        } else {
            panel.orderFront(sender)
        }
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
                size: initialWindowSize
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
        panel.collectionBehavior = Self.collectionBehavior(joinsAllSpaces: joinsAllSpaces)
        panel.tabbingMode = .disallowed
        if usesSavedFrame {
            panel.setFrameAutosaveName(Self.frameAutosaveName)
        }
        panel.level = state.pinned ? .floating : .normal
        panel.minSize = DashboardLayoutMetrics.minimumWindowSize
        panel.center()
        panel.contentView = NSHostingView(
            rootView: DashboardView(
                state: state,
                conversationFixtureModuleID: conversationFixtureModuleID,
                conversationFixtureUsesRecorderNormalizer:
                    conversationFixtureUsesRecorderNormalizer
            )
        )
        state.onPinnedChange = { [weak panel] isPinned in
            panel?.level = isPinned ? .floating : .normal
        }
        self.panel = panel
        return panel
    }
}

@MainActor
final class DashboardState: ObservableObject {
    @Published var pinned: Bool { didSet { onPinnedChange?(pinned) } }
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
    private let liveClient: LoopbackOperationsSnapshotClient?
    private var isRefreshing = false

    init(
        snapshotURL: URL? = nil,
        initialPinned: Bool = false,
        liveClient: LoopbackOperationsSnapshotClient? = LoopbackOperationsSnapshotClient()
    ) {
        pinned = initialPinned
        store = LocalSnapshotStore(snapshotURL: snapshotURL ?? Self.defaultSnapshotURL)
        self.liveClient = liveClient
        snapshot = .emptyLocal
        sourceDescription = "No live or saved operations — lanes empty"
        canRestorePreviousSnapshot = false
        reload()
    }

    func reload() {
        guard let decoded = store.load() else {
            snapshot = .emptyLocal
            sourceDescription = "No live or saved operations — lanes empty"
            canRestorePreviousSnapshot = store.hasValidPreviousSnapshot()
            return
        }
        use(decoded)
    }

    func refreshPreferredSource() async {
        guard !isRefreshing else { return }
        isRefreshing = true
        defer { isRefreshing = false }

        if let liveClient, let liveSnapshot = try? await liveClient.fetch() {
            use(
                liveSnapshot,
                sourceDescription: "Live loopback operations — local only"
            )
            return
        }
        reload()
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

    private func use(
        _ decoded: DashboardSnapshot,
        sourceDescription override: String? = nil
    ) {
        snapshot = decoded
        sourceDescription = override
            ?? (
                decoded.mode == .local
                    ? "Locally verified snapshot — refreshes automatically"
                    : "Sanitized snapshot — refreshes automatically"
            )
        canRestorePreviousSnapshot = store.hasValidPreviousSnapshot()
    }
}

private struct DashboardView: View {
    @StateObject private var state: DashboardState
    @StateObject private var chat: RouterChatSession
    @State private var didPrepareConversationFixture = false
    @AppStorage("OperationsFloater.GuideCollapsedV1")
    private var guideCollapsed = false
    @AppStorage("OperationsFloater.AssistantCollapsedV1")
    private var assistantCollapsed = false
    @AppStorage("OperationsFloater.ResourcesCollapsedV1")
    private var resourcesCollapsed = false
    @AppStorage("OperationsFloater.RacesCollapsedV1")
    private var racesCollapsed = false
    @AppStorage("OperationsFloater.TestsCollapsedV1")
    private var testsCollapsed = false
    @AppStorage("OperationsFloater.SignalsCollapsedV1")
    private var signalsCollapsed = false
    private let conversationFixtureModuleID: String?
    private let conversationFixtureUsesRecorderNormalizer: Bool

    init(
        state: DashboardState,
        conversationFixtureModuleID: String? = nil,
        conversationFixtureUsesRecorderNormalizer: Bool = false
    ) {
        _state = StateObject(wrappedValue: state)
        _chat = StateObject(wrappedValue: RouterChatSession())
        self.conversationFixtureModuleID = conversationFixtureModuleID
        self.conversationFixtureUsesRecorderNormalizer =
            conversationFixtureUsesRecorderNormalizer
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
                        RouterChatPanel(
                            session: chat,
                            metrics: metrics,
                            isCollapsed: $assistantCollapsed
                        )
                        resourceBudgetPanel(metrics: metrics)
                        QueueRaceBoard(
                            records: state.snapshot.queue,
                            metrics: metrics,
                            isCollapsed: $racesCollapsed
                        )
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
        .task {
            await state.refreshPreferredSource()
            guard let conversationFixtureModuleID,
                  !didPrepareConversationFixture else {
                return
            }
            didPrepareConversationFixture = true
            await chat.prepareSyntheticConversationUITest(
                moduleID: conversationFixtureModuleID,
                usesNaturalRecorderNormalization:
                    conversationFixtureUsesRecorderNormalizer
            )
        }
        .onReceive(Timer.publish(every: 2, on: .main, in: .common).autoconnect()) { _ in
            guard hasActiveSnapshotConsumers else { return }
            Task {
                await state.refreshPreferredSource()
            }
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
            HStack {
                Text("LOCAL PROCEDURAL GUIDE")
                    .font(.caption2.weight(.bold))
                    .foregroundStyle(.secondary)
                Spacer(minLength: 0)
                collapseButton(
                    title: "Local procedural guide",
                    isCollapsed: $guideCollapsed
                )
            }

            if !guideCollapsed {
                Divider()
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
            isCollapsed: $resourcesCollapsed,
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

    private func supportingGrid(metrics: DashboardLayoutMetrics) -> some View {
        LazyVGrid(
            columns: gridColumns(metrics: metrics),
            alignment: .leading,
            spacing: metrics.sectionSpacing
        ) {
            dashboardPanel(
                title: "Tests and quality",
                subtitle: "\(state.snapshot.tests.count) records",
                isCollapsed: $testsCollapsed,
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
                isCollapsed: $signalsCollapsed,
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
        isCollapsed: Binding<Bool>,
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
                collapseButton(title: title, isCollapsed: isCollapsed)
            }
            .padding(.horizontal, metrics.recordPadding)
            .padding(.vertical, 7)
            if !isCollapsed.wrappedValue {
                Divider()
                content()
            }
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

    private var hasActiveSnapshotConsumers: Bool {
        DashboardPanelActivity.shouldRefreshSnapshot(
            guideCollapsed: guideCollapsed,
            resourcesCollapsed: resourcesCollapsed,
            racesCollapsed: racesCollapsed,
            testsCollapsed: testsCollapsed,
            signalsCollapsed: signalsCollapsed
        )
    }

    private func collapseButton(
        title: String,
        isCollapsed: Binding<Bool>
    ) -> some View {
        Button {
            isCollapsed.wrappedValue.toggle()
        } label: {
            Image(
                systemName: isCollapsed.wrappedValue
                    ? "chevron.right"
                    : "chevron.down"
            )
        }
        .buttonStyle(.plain)
        .accessibilityLabel(
            "\(isCollapsed.wrappedValue ? "Expand" : "Collapse") \(title)"
        )
    }

}

enum DashboardPanelActivity {
    static func shouldRefreshSnapshot(
        guideCollapsed: Bool,
        resourcesCollapsed: Bool,
        racesCollapsed: Bool,
        testsCollapsed: Bool,
        signalsCollapsed: Bool
    ) -> Bool {
        !guideCollapsed
            || !resourcesCollapsed
            || !racesCollapsed
            || !testsCollapsed
            || !signalsCollapsed
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
