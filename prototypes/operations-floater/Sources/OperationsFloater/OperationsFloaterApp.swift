// The executable entry point is intentionally not named main.swift: SwiftPM
// reserves that filename for top-level program code, which conflicts with @main.
import AppKit
import SwiftUI

@main
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private static let shared = AppDelegate()
    private var panel: NSWindow?
    private let dashboardState = DashboardState()

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
        let panel = panel ?? makeDashboardWindow()
        panel.level = dashboardState.pinned ? .floating : .normal
        panel.makeKeyAndOrderFront(sender)
        panel.orderFrontRegardless()
        NSApplication.shared.activate(ignoringOtherApps: true)
    }

    @objc private func closeDashboard(_ sender: Any?) {
        panel?.performClose(sender)
    }

    private func makeDashboardWindow() -> NSWindow {
        let content = DashboardView(state: dashboardState)
        let panel = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 380, height: 560),
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
        // Stay readable above ordinary app windows while pinned.
        panel.level = .floating
        panel.minSize = NSSize(width: 320, height: 400)
        panel.center()
        panel.contentView = NSHostingView(rootView: content)
        dashboardState.onPinnedChange = { [weak panel] isPinned in
            panel?.level = isPinned ? .floating : .normal
        }
        self.panel = panel
        return panel
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

struct WorkItem: Identifiable, Hashable {
    enum State: String, Decodable { case running = "running", next = "next", waiting = "waiting" }
    let id: String
    let title: String
    let detail: String
    let state: State
}

private struct DashboardFile: Decodable {
    let items: [WorkItem]
}

extension WorkItem: Decodable {}

@MainActor
final class DashboardState: ObservableObject {
    @Published var pinned = true { didSet { onPinnedChange?(pinned) } }
    @Published private(set) var items: [WorkItem]
    @Published private(set) var sourceDescription: String
    var onPinnedChange: ((Bool) -> Void)?

    private static let sampleItems = [
        WorkItem(
            id: "example-running",
            title: "Example work item",
            detail: "Replace with local state.",
            state: .running
        ),
        WorkItem(
            id: "example-next",
            title: "Example queued item",
            detail: "Awaiting a local update.",
            state: .next
        )
    ]

    private static let defaultQueueURL: URL = {
        let applicationSupport = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first!
        return applicationSupport
            .appendingPathComponent("OperationsFloater", isDirectory: true)
            .appendingPathComponent("dashboard-state.json")
    }()
    private let queueURL: URL

    init(queueURL: URL? = nil) {
        self.queueURL = queueURL ?? Self.defaultQueueURL
        items = Self.sampleItems
        sourceDescription = "Generic sample — local only"
        reload()
    }

    func reload() {
        guard let data = try? Data(contentsOf: queueURL),
              let file = try? JSONDecoder().decode(DashboardFile.self, from: data) else {
            items = Self.sampleItems
            sourceDescription = "Generic sample — local only"
            return
        }
        items = file.items
        sourceDescription = "Local queue — refreshes automatically"
    }

    func itemCount(for stateToCount: WorkItem.State) -> Int {
        items.lazy.filter { $0.state == stateToCount }.count
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
                    summary
                    lane(title: "Running", state: .running, items: state.items)
                    lane(title: "Up next", state: .next, items: state.items)
                    lane(title: "Waiting on you", state: .waiting, items: state.items)
                }
                .padding(18)
            }
        }
        .frame(minWidth: 320, minHeight: 400)
        .background(.regularMaterial)
        .onReceive(Timer.publish(every: 2, on: .main, in: .common).autoconnect()) { _ in state.reload() }
    }

    private var avatar: some View {
        HStack(spacing: 14) {
            AnimatedGuideAvatar()
                .frame(width: 92, height: 92)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 6) {
                Text("Queue guide").font(.headline)
                Text(state.items.contains(where: { $0.state == .running })
                     ? "I’m tracking the active lane."
                     : "Your queue is clear for now.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
        .padding(14)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 16))
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("Operations dashboard").font(.headline)
                Text(state.sourceDescription)
                    .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Toggle("Keep in front", isOn: $state.pinned)
                .toggleStyle(.switch).controlSize(.small)
                .accessibilityLabel("Keep dashboard in front")
        }
        .padding(16)
    }

    private var summary: some View {
        HStack(spacing: 10) {
            metric(count(for: .running), "running", .blue)
            metric(count(for: .next), "next", .orange)
            metric(count(for: .waiting), "waiting", .purple)
        }
    }

    private func count(for stateToCount: WorkItem.State) -> String {
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

    private func lane(title: String, state: WorkItem.State, items: [WorkItem]) -> some View {
        let selected = items.filter { $0.state == state }
        return VStack(alignment: .leading, spacing: 8) {
            Text(title.uppercased()).font(.caption.weight(.semibold)).foregroundStyle(.secondary)
            ForEach(selected) { item in
                VStack(alignment: .leading, spacing: 4) {
                    Text(item.title).font(.body.weight(.medium))
                    Text(item.detail).font(.caption).foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(12)
                .background(.quaternary, in: RoundedRectangle(cornerRadius: 10))
            }
        }
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
                    .fill(AngularGradient(colors: [.indigo, .cyan, .mint, .indigo], center: .center))
                    .opacity(0.23)
                    .scaleEffect(pulse)
                Circle()
                    .fill(.ultraThinMaterial)
                    .overlay(Circle().stroke(.white.opacity(0.38), lineWidth: 1))
                    .padding(7)

                // Head and ears
                Circle().fill(Color.indigo.opacity(0.95)).frame(width: 54, height: 54)
                    .offset(y: bob)
                Circle().fill(Color.indigo.opacity(0.85)).frame(width: 17, height: 17)
                    .offset(x: -27, y: bob + 4)
                Circle().fill(Color.indigo.opacity(0.85)).frame(width: 17, height: 17)
                    .offset(x: 27, y: bob + 4)

                // Friendly eyes and smile.
                HStack(spacing: 13) {
                    Capsule().fill(.white).frame(width: 7, height: 10 * blink)
                    Capsule().fill(.white).frame(width: 7, height: 10 * blink)
                }
                .offset(y: bob - 5)
                Capsule().fill(.white.opacity(0.9)).frame(width: 18, height: 4)
                    .offset(y: bob + 13)

                // One small waving arm gives the character a visible idle motion.
                Capsule().fill(Color.cyan.opacity(0.9)).frame(width: 10, height: 29)
                    .rotationEffect(.degrees(-35 + wave))
                    .offset(x: 31, y: bob + 29)
            }
            .drawingGroup()
        }
    }
}
