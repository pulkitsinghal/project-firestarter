// The executable entry point is intentionally not named main.swift: SwiftPM
// reserves that filename for top-level program code, which conflicts with @main.
import AppKit
import SwiftUI

@main
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private static let shared = AppDelegate()
    private var panel: NSWindow?

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
        let content = DashboardView()
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
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .moveToActiveSpace]
        // Stay readable above ordinary app windows while pinned.
        panel.level = .floating
        panel.minSize = NSSize(width: 320, height: 400)
        panel.center()
        panel.contentView = NSHostingView(rootView: content)
        panel.makeKeyAndOrderFront(nil)
        panel.orderFrontRegardless()
        NSApplication.shared.activate(ignoringOtherApps: true)
        self.panel = panel
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak panel] in
            panel?.makeKeyAndOrderFront(nil)
            panel?.orderFrontRegardless()
            NSApplication.shared.activate(ignoringOtherApps: true)
        }
    }
}

private struct WorkItem: Identifiable, Hashable {
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
private final class DashboardState: ObservableObject {
    @Published var pinned = true { didSet { updateWindowLevel() } }
    @Published var items: [WorkItem] = []
    private let queueURL: URL = {
        let applicationSupport = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first!
        return applicationSupport
            .appendingPathComponent("OperationsFloater", isDirectory: true)
            .appendingPathComponent("dashboard-state.json")
    }()

    init() { reload() }

    func reload() {
        guard let data = try? Data(contentsOf: queueURL),
              let file = try? JSONDecoder().decode(DashboardFile.self, from: data) else { return }
        items = file.items
    }

    func updateWindowLevel() {
        NSApplication.shared.windows.first(where: { $0.title == "Operations dashboard" })?.level = pinned ? .floating : .normal
    }
}

private struct DashboardView: View {
    @StateObject private var state = DashboardState()

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
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
        .onAppear { state.updateWindowLevel() }
        .onReceive(Timer.publish(every: 2, on: .main, in: .common).autoconnect()) { _ in state.reload() }
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("Operations dashboard").font(.headline)
                Text("Local queue — refreshes automatically")
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
            metric("1", "running", .blue)
            metric("2", "next", .orange)
            metric("1", "waiting", .purple)
        }
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
