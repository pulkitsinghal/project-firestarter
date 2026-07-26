import AppKit
import Foundation
import Testing
@testable import OperationsFloater

@Suite("Dashboard state")
@MainActor
struct DashboardStateTests {
    @Test("Missing local state uses the canonical generic sample")
    func missingLocalStateUsesSample() {
        let state = DashboardState(snapshotURL: missingFixtureURL())

        #expect(state.snapshot == .sample)
        #expect(state.sourceDescription == "Generic sample — local only")
        #expect(state.itemCount(for: .running) == 1)
        #expect(state.itemCount(for: .queued) == 1)
        #expect(state.itemCount(for: .waiting) == 0)
        #expect(state.snapshot.resourceBudget.first?.verification == .unavailable)
    }

    @Test("The native fallback exactly matches the shared committed fixture")
    func nativeSampleMatchesSharedFixture() throws {
        let fixtureURL = packageRoot()
            .deletingLastPathComponent()
            .appendingPathComponent("operations-dashboard/contract/dashboard-state.sample.json")
        let fixture = try DashboardSnapshot.decodeValidated(from: Data(contentsOf: fixtureURL))

        #expect(fixture == .sample)
    }

    @Test("Valid local state drives all canonical record sections")
    func validLocalStateDrivesSharedModel() throws {
        let fixtureURL = try makeFixture(contents: localFixture(verification: "verified"))
        defer { try? FileManager.default.removeItem(at: fixtureURL.deletingLastPathComponent()) }

        let state = DashboardState(snapshotURL: fixtureURL)

        #expect(state.snapshot.mode == .local)
        #expect(state.sourceDescription == "Locally verified snapshot — refreshes automatically")
        #expect(state.itemCount(for: .running) == 1)
        #expect(state.itemCount(for: .queued) == 0)
        #expect(state.itemCount(for: .waiting) == 2)
        #expect(state.snapshot.tests.first?.result == .queued)
        #expect(state.snapshot.resourceBudget.first?.displayValue == "Busy")
        #expect(state.snapshot.signals.first?.verification == .verified)
    }

    @Test("Draft contract aliases fail closed to the generic sample")
    func legacyShapeUsesSample() throws {
        let legacy = localFixture(verification: "verified")
            .replacingOccurrences(of: #""mode": "local""#, with: #""snapshotKind": "local""#)
            .replacingOccurrences(of: #""tests":"#, with: #""qualityChecks":"#)
        let fixtureURL = try makeFixture(contents: legacy)
        defer { try? FileManager.default.removeItem(at: fixtureURL.deletingLastPathComponent()) }

        let state = DashboardState(snapshotURL: fixtureURL)

        #expect(state.snapshot == .sample)
    }

    @Test("Unverified local records fail closed")
    func unverifiedLocalRecordUsesSample() throws {
        let fixtureURL = try makeFixture(contents: localFixture(verification: "estimated"))
        defer { try? FileManager.default.removeItem(at: fixtureURL.deletingLastPathComponent()) }

        let state = DashboardState(snapshotURL: fixtureURL)

        #expect(state.snapshot == .sample)
        #expect(state.snapshot.signals.first?.verification == .notImplemented)
        #expect(state.snapshot.signals.first?.exposure == .sanitized)
    }

    @Test("Window opens frontmost, unpins, closes, and reopens as the same retained window")
    func windowLifecycleAndPinning() {
        _ = NSApplication.shared
        let state = DashboardState(snapshotURL: missingFixtureURL())
        let controller = DashboardWindowController(state: state, activatesApplication: false)

        let firstWindow = controller.show()
        #expect(firstWindow.isVisible)
        #expect(firstWindow.level == .floating)

        state.pinned = false
        #expect(firstWindow.level == .normal)

        controller.close()
        #expect(!firstWindow.isVisible)

        let reopenedWindow = controller.show()
        #expect(reopenedWindow === firstWindow)
        #expect(reopenedWindow.isVisible)
        #expect(reopenedWindow.level == .normal)
        controller.close()
    }

    private func missingFixtureURL() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
            .appendingPathComponent("dashboard-state.json")
    }

    private func packageRoot() -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
    }

    private func makeFixture(contents: String) throws -> URL {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("OperationsFloaterTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let fixtureURL = directory.appendingPathComponent("dashboard-state.json")
        try Data(contents.utf8).write(to: fixtureURL, options: .atomic)
        return fixtureURL
    }

    private func localFixture(verification: String) -> String {
        """
        {
          "schemaVersion": "1.0",
          "mode": "local",
          "queue": [
            {
              "id": "Q1",
              "title": "Example one",
              "detail": "Local record",
              "state": "running",
              "exposure": "local-only",
              "verification": "\(verification)"
            },
            {
              "id": "Q2",
              "title": "Example two",
              "detail": "Local record",
              "state": "waiting",
              "exposure": "local-only",
              "verification": "\(verification)"
            },
            {
              "id": "Q3",
              "title": "Example three",
              "detail": "Local record",
              "state": "waiting",
              "exposure": "local-only",
              "verification": "\(verification)"
            }
          ],
          "tests": [
            {
              "id": "T1",
              "title": "Local check",
              "detail": "Queued locally",
              "result": "queued",
              "exposure": "local-only",
              "verification": "\(verification)"
            }
          ],
          "resourceBudget": [
            {
              "id": "R1",
              "title": "Heavy validation lane",
              "detail": "A bounded task is active.",
              "displayValue": "Busy",
              "exposure": "local-only",
              "verification": "\(verification)"
            }
          ],
          "signals": [
            {
              "id": "S1",
              "title": "Local signal",
              "detail": "Verified at runtime.",
              "state": "available",
              "exposure": "local-only",
              "verification": "\(verification)"
            }
          ]
        }
        """
    }
}
