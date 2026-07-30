import Foundation
import Testing
@testable import OperationsFloater

@Suite("Dashboard state")
@MainActor
struct DashboardStateTests {
    @Test("Missing local state falls back to generic sample data")
    func missingLocalStateUsesSample() {
        let missingURL = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
            .appendingPathComponent("dashboard-state.json")
        let state = DashboardState(queueURL: missingURL)

        #expect(state.sourceDescription == "Generic sample — local only")
        #expect(state.itemCount(for: .running) == 1)
        #expect(state.itemCount(for: .next) == 1)
        #expect(state.itemCount(for: .waiting) == 0)
    }

    @Test("Valid local state drives the visible counts")
    func validLocalStateDrivesCounts() throws {
        let fixture = """
        {
          "items": [
            {"id":"run-1","title":"Example one","detail":"Local only","state":"running"},
            {"id":"wait-1","title":"Example two","detail":"Local only","state":"waiting"},
            {"id":"wait-2","title":"Example three","detail":"Local only","state":"waiting"}
          ]
        }
        """
        let fixtureURL = try makeFixture(contents: fixture)
        defer { try? FileManager.default.removeItem(at: fixtureURL.deletingLastPathComponent()) }

        let state = DashboardState(queueURL: fixtureURL)

        #expect(state.sourceDescription == "Local queue — refreshes automatically")
        #expect(state.itemCount(for: .running) == 1)
        #expect(state.itemCount(for: .next) == 0)
        #expect(state.itemCount(for: .waiting) == 2)
    }

    @Test("Invalid local state fails closed to generic sample data")
    func invalidLocalStateUsesSample() throws {
        let fixtureURL = try makeFixture(contents: #"{"items":[{"state":"unknown"}]}"#)
        defer { try? FileManager.default.removeItem(at: fixtureURL.deletingLastPathComponent()) }

        let state = DashboardState(queueURL: fixtureURL)

        #expect(state.sourceDescription == "Generic sample — local only")
        #expect(state.itemCount(for: .running) == 1)
        #expect(state.itemCount(for: .next) == 1)
        #expect(state.itemCount(for: .waiting) == 0)
    }

    @Test("Unpinning notifies the window-level adapter")
    func unpinNotifiesWindowAdapter() {
        let missingURL = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
            .appendingPathComponent("dashboard-state.json")
        let state = DashboardState(queueURL: missingURL)
        var observedPinnedState: Bool?
        state.onPinnedChange = { observedPinnedState = $0 }

        state.pinned = false

        #expect(observedPinnedState == false)
    }

    private func makeFixture(contents: String) throws -> URL {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("OperationsFloaterTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let fixtureURL = directory.appendingPathComponent("dashboard-state.json")
        try Data(contents.utf8).write(to: fixtureURL, options: .atomic)
        return fixtureURL
    }
}
