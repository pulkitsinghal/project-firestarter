import AppKit
import Foundation
import Testing
@testable import OperationsFloater

@Suite("Dashboard state")
@MainActor
struct DashboardStateTests {
    @Test("Interactive launch is unpinned while retaining explicit foreground behavior")
    func interactiveLaunchConfiguration() {
        let configuration = DashboardLaunchConfiguration(arguments: ["/tmp/Operations Floater"])

        #expect(!configuration.isBackgroundUITest)
        #expect(!configuration.initialPinned)
        #expect(configuration.activatesApplication)
        #expect(configuration.foregroundsWindow)
        #expect(configuration.joinsAllSpaces)
        #expect(configuration.usesSavedFrame)
        #expect(!configuration.usesSyntheticConversationFixture)
    }

    @Test("Background UI testing is unpinned, nonactivating, and single-Space")
    func backgroundUITestLaunchConfiguration() {
        let configuration = DashboardLaunchConfiguration(
            arguments: [
                "/tmp/Operations Floater",
                DashboardLaunchConfiguration.backgroundUITestArgument,
                DashboardLaunchConfiguration.syntheticConversationUITestArgument,
                DashboardLaunchConfiguration.compactUITestArgument,
            ]
        )

        #expect(configuration.isBackgroundUITest)
        #expect(!configuration.initialPinned)
        #expect(!configuration.activatesApplication)
        #expect(!configuration.foregroundsWindow)
        #expect(!configuration.joinsAllSpaces)
        #expect(!configuration.usesSavedFrame)
        #expect(configuration.usesSyntheticConversationFixture)
        #expect(
            configuration.initialWindowSize
                == DashboardLayoutMetrics.minimumWindowSize
        )
    }

    @Test("Background UI testing starts with Keep in front disabled")
    func backgroundUITestInitialPinning() {
        let state = DashboardState(
            snapshotURL: missingFixtureURL(),
            initialPinned: false,
            liveClient: nil
        )

        #expect(!state.pinned)
    }

    @Test("Missing local state renders every lane empty")
    func missingLocalStateUsesEmptySnapshot() {
        let state = DashboardState(snapshotURL: missingFixtureURL(), liveClient: nil)

        #expect(state.snapshot == .emptyLocal)
        #expect(state.sourceDescription == "No live or saved operations — lanes empty")
        #expect(state.itemCount(for: .running) == 0)
        #expect(state.itemCount(for: .queued) == 0)
        #expect(state.itemCount(for: .waiting) == 0)
        #expect(state.itemCount(for: .ready) == 0)
        #expect(state.snapshot.queue.isEmpty)
        #expect(state.snapshot.resourceBudget.isEmpty)
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

        let state = DashboardState(snapshotURL: fixtureURL, liveClient: nil)

        #expect(state.snapshot.mode == .local)
        #expect(state.sourceDescription == "Locally verified snapshot — refreshes automatically")
        #expect(state.itemCount(for: .running) == 1)
        #expect(state.itemCount(for: .queued) == 0)
        #expect(state.itemCount(for: .waiting) == 2)
        #expect(state.snapshot.tests.first?.result == .queued)
        #expect(state.snapshot.resourceBudget.first?.displayValue == "Busy")
        #expect(state.snapshot.signals.first?.verification == .verified)
        #expect(state.snapshot.queue.first?.completedSteps == 3)
        #expect(state.snapshot.queue.first?.totalSteps == 5)
        #expect(state.snapshot.queue.first?.cpuPercent == 42.5)
    }

    @Test("Draft contract aliases fail closed to an empty dashboard")
    func legacyShapeUsesEmptySnapshot() throws {
        let legacy = localFixture(verification: "verified")
            .replacingOccurrences(of: #""mode": "local""#, with: #""snapshotKind": "local""#)
            .replacingOccurrences(of: #""tests":"#, with: #""qualityChecks":"#)
        let fixtureURL = try makeFixture(contents: legacy)
        defer { try? FileManager.default.removeItem(at: fixtureURL.deletingLastPathComponent()) }

        let state = DashboardState(snapshotURL: fixtureURL, liveClient: nil)

        #expect(state.snapshot == .emptyLocal)
    }

    @Test("Unverified local records fail closed")
    func unverifiedLocalRecordUsesSample() throws {
        let fixtureURL = try makeFixture(contents: localFixture(verification: "estimated"))
        defer { try? FileManager.default.removeItem(at: fixtureURL.deletingLastPathComponent()) }

        let state = DashboardState(snapshotURL: fixtureURL, liveClient: nil)

        #expect(state.snapshot == .emptyLocal)
        #expect(state.snapshot.signals.isEmpty)
    }

    @Test("Import installs a validated local snapshot with private file permissions")
    func importInstallsLocalSnapshot() throws {
        let directory = try makeTemporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let sourceURL = directory.appendingPathComponent("source.json")
        let installedURL = directory
            .appendingPathComponent("ApplicationSupport", isDirectory: true)
            .appendingPathComponent("dashboard-state.json")
        try Data(localFixture(verification: "verified").utf8).write(to: sourceURL)
        let state = DashboardState(snapshotURL: installedURL, liveClient: nil)

        try state.importLocalSnapshot(from: sourceURL)

        #expect(state.snapshot.mode == .local)
        #expect(state.sourceDescription == "Locally verified snapshot — refreshes automatically")
        #expect(!state.canRestorePreviousSnapshot)
        let attributes = try FileManager.default.attributesOfItem(atPath: installedURL.path)
        #expect((attributes[.posixPermissions] as? NSNumber)?.intValue == 0o600)
    }

    @Test("Update retains the previous valid snapshot and rollback swaps it back")
    func updateAndRollbackLocalSnapshot() throws {
        let directory = try makeTemporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let sourceURL = directory.appendingPathComponent("source.json")
        let installedURL = directory
            .appendingPathComponent("ApplicationSupport", isDirectory: true)
            .appendingPathComponent("dashboard-state.json")
        let state = DashboardState(snapshotURL: installedURL, liveClient: nil)

        try Data(
            localFixture(verification: "verified", queueTitle: "First version").utf8
        ).write(to: sourceURL)
        try state.importLocalSnapshot(from: sourceURL)

        try Data(
            localFixture(verification: "verified", queueTitle: "Second version").utf8
        ).write(to: sourceURL)
        try state.importLocalSnapshot(from: sourceURL)
        #expect(state.snapshot.queue.first?.title == "Second version")
        #expect(state.canRestorePreviousSnapshot)

        try state.restorePreviousSnapshot()
        #expect(state.snapshot.queue.first?.title == "First version")
        #expect(state.canRestorePreviousSnapshot)
    }

    @Test("A rejected update cannot replace the active local snapshot")
    func rejectedUpdatePreservesActiveSnapshot() throws {
        let directory = try makeTemporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let sourceURL = directory.appendingPathComponent("source.json")
        let installedURL = directory.appendingPathComponent("dashboard-state.json")
        let state = DashboardState(snapshotURL: installedURL, liveClient: nil)

        try Data(
            localFixture(verification: "verified", queueTitle: "Accepted version").utf8
        ).write(to: sourceURL)
        try state.importLocalSnapshot(from: sourceURL)

        try Data(
            localFixture(verification: "estimated", queueTitle: "Rejected version").utf8
        ).write(to: sourceURL)
        #expect(throws: DashboardSnapshot.ValidationError.self) {
            try state.importLocalSnapshot(from: sourceURL)
        }
        state.reload()

        #expect(state.snapshot.queue.first?.title == "Accepted version")
        #expect(!state.canRestorePreviousSnapshot)
    }

    @Test("The local import adapter rejects a non-local canonical snapshot")
    func importRejectsNonLocalSnapshot() throws {
        let directory = try makeTemporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let sourceURL = packageRoot()
            .deletingLastPathComponent()
            .appendingPathComponent("operations-dashboard/contract/dashboard-state.sample.json")
        let store = LocalSnapshotStore(
            snapshotURL: directory.appendingPathComponent("dashboard-state.json")
        )

        #expect(throws: LocalSnapshotStore.StoreError.localModeRequired) {
            try store.importLocalSnapshot(from: sourceURL)
        }
    }

    @Test("The local import adapter rejects oversized input before decoding")
    func importRejectsOversizedInput() throws {
        let directory = try makeTemporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = LocalSnapshotStore(
            snapshotURL: directory.appendingPathComponent("dashboard-state.json")
        )
        let oversized = Data(count: LocalSnapshotStore.maximumSnapshotBytes + 1)

        #expect(throws: LocalSnapshotStore.StoreError.sourceTooLarge) {
            try store.installLocalSnapshot(data: oversized)
        }
    }

    @Test("Native validation enforces the shared record length limits")
    func recordLengthLimitFailsClosed() throws {
        let oversizedTitle = String(repeating: "A", count: 121)
        let fixtureURL = try makeFixture(
            contents: localFixture(
                verification: "verified",
                queueTitle: oversizedTitle
            )
        )
        defer { try? FileManager.default.removeItem(at: fixtureURL.deletingLastPathComponent()) }

        let state = DashboardState(snapshotURL: fixtureURL, liveClient: nil)

        #expect(state.snapshot == .emptyLocal)
    }

    @Test("Invalid or unpaired progress evidence fails closed")
    func invalidProgressFailsClosed() throws {
        let invalid = localFixture(verification: "verified")
            .replacingOccurrences(of: #""totalSteps": 5"#, with: #""totalSteps": 2"#)
        let fixtureURL = try makeFixture(contents: invalid)
        defer { try? FileManager.default.removeItem(at: fixtureURL.deletingLastPathComponent()) }

        let state = DashboardState(snapshotURL: fixtureURL, liveClient: nil)

        #expect(state.snapshot == .emptyLocal)
    }

    @Test("Window opens frontmost, unpins, closes, and reopens as the same retained window")
    func windowLifecycleAndPinning() {
        _ = NSApplication.shared
        let state = DashboardState(
            snapshotURL: missingFixtureURL(),
            initialPinned: true,
            liveClient: nil
        )
        let controller = DashboardWindowController(state: state, activatesApplication: false)

        let firstWindow = controller.show()
        #expect(firstWindow.isVisible)
        #expect(firstWindow.level == .floating)
        #expect(firstWindow.minSize == DashboardLayoutMetrics.minimumWindowSize)
        #expect(
            firstWindow.frameAutosaveName
                == NSWindow.FrameAutosaveName(DashboardWindowController.frameAutosaveName)
        )

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

    @Test("Single-Space presentation does not opt into following the user")
    func singleSpaceWindowPresentation() {
        let behavior = DashboardWindowController.collectionBehavior(joinsAllSpaces: false)

        #expect(behavior.contains(.managed))
        #expect(!behavior.contains(.canJoinAllSpaces))
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
        let directory = try makeTemporaryDirectory()
        let fixtureURL = directory.appendingPathComponent("dashboard-state.json")
        try Data(contents.utf8).write(to: fixtureURL, options: .atomic)
        return fixtureURL
    }

    private func makeTemporaryDirectory() throws -> URL {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("OperationsFloaterTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory
    }

    private func localFixture(
        verification: String,
        queueTitle: String = "Example one"
    ) -> String {
        """
        {
          "schemaVersion": "1.0",
          "mode": "local",
          "queue": [
            {
              "id": "Q1",
              "title": "\(queueTitle)",
              "detail": "Local record",
              "state": "running",
              "exposure": "local-only",
              "verification": "\(verification)",
              "completedSteps": 3,
              "totalSteps": 5,
              "currentStep": "Synthetic verification",
              "lastActiveSeconds": 12,
              "memoryMB": 768,
              "cpuPercent": 42.5
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
