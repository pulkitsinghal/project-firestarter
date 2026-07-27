import AppKit
import Foundation
import Testing
@testable import OperationsFloater

@Suite("Guide presentation")
struct GuidePresentationTests {
    @Test("Motion frames are deterministic for the same inputs")
    func motionIsDeterministic() {
        let first = GuideMotionSampler.frame(
            at: 12.375,
            activity: .active,
            reduceMotion: false
        )
        let second = GuideMotionSampler.frame(
            at: 12.375,
            activity: .active,
            reduceMotion: false
        )

        #expect(first == second)
        #expect(first != .still)
    }

    @Test("Reduce Motion produces a stable frame for every guide state")
    func reduceMotionIsStable() {
        let activities: [GuideActivity] = [.attention, .active, .ready, .waiting, .idle]

        for activity in activities {
            #expect(
                GuideMotionSampler.frame(
                    at: 8_942.5,
                    activity: activity,
                    reduceMotion: true
                ) == .still
            )
        }
    }

    @Test("Blink timing is deterministic and bounded")
    func deterministicBlink() {
        let open = GuideMotionSampler.frame(
            at: 3.5,
            activity: .active,
            reduceMotion: false
        )
        let closed = GuideMotionSampler.frame(
            at: 3.9,
            activity: .active,
            reduceMotion: false
        )

        #expect(open.eyeScale == 1)
        #expect(closed.eyeScale == 0.14)
        #expect(abs(closed.bob) <= 3.1)
        #expect(abs(closed.wave) <= 11)
        #expect((0.96...1.04).contains(closed.pulse))
    }

    @Test("Guide state gives verified attention priority over active work")
    func verifiedAttentionHasPriority() {
        let snapshot = makeSnapshot(
            queue: [
                QueueRecord(
                    id: "Q1",
                    title: "Active example",
                    detail: "Generic record.",
                    state: .running,
                    exposure: .sanitized,
                    verification: .estimated
                )
            ],
            tests: [
                TestRecord(
                    id: "T1",
                    title: "Verified failure",
                    detail: "Generic record.",
                    result: .failed,
                    exposure: .sanitized,
                    verification: .verified
                )
            ]
        )

        #expect(snapshot.guideCue.activity == .attention)
        #expect(snapshot.guideCue.title == "Verified attention needed")
        #expect(snapshot.guideCue.detail == "1 verified item needs a decision.")
    }

    @Test("Unverified failure does not become an attention cue")
    func unverifiedFailureDoesNotEscalate() {
        let snapshot = makeSnapshot(
            queue: [
                QueueRecord(
                    id: "Q1",
                    title: "Queued example",
                    detail: "Generic record.",
                    state: .queued,
                    exposure: .sanitized,
                    verification: .estimated
                )
            ],
            tests: [
                TestRecord(
                    id: "T1",
                    title: "Estimated failure",
                    detail: "Generic record.",
                    result: .failed,
                    exposure: .sanitized,
                    verification: .estimated
                )
            ]
        )

        #expect(snapshot.guideCue.activity == .ready)
        #expect(snapshot.guideCue.title == "Next work is staged")
    }

    @Test("Guide cue deterministically covers waiting and empty queues")
    func waitingAndIdleCues() {
        let waiting = makeSnapshot(
            queue: [
                QueueRecord(
                    id: "Q1",
                    title: "Waiting example",
                    detail: "Generic record.",
                    state: .waiting,
                    exposure: .sanitized,
                    verification: .estimated
                )
            ]
        )
        let idle = makeSnapshot()

        #expect(waiting.guideCue.activity == .waiting)
        #expect(waiting.guideCue.detail == "1 item is waiting for a dependency.")
        #expect(idle.guideCue.activity == .idle)
        #expect(idle.guideCue.detail == "No operational work is currently supplied.")
    }

    @Test("Compact and dense layouts switch at one deterministic breakpoint")
    func layoutBreakpoint() {
        let compact = DashboardLayoutMetrics(
            width: DashboardLayoutMetrics.denseBreakpoint - 1
        )
        let dense = DashboardLayoutMetrics(
            width: DashboardLayoutMetrics.denseBreakpoint
        )

        #expect(compact.density == .compact)
        #expect(compact.columnCount == 1)
        #expect(dense.density == .dense)
        #expect(dense.columnCount == 2)
        #expect(compact.estimatedCardWidth(containerWidth: 559) == 531)
        #expect(dense.estimatedCardWidth(containerWidth: 560) == 263)
    }

    @Test("Default and minimum windows preserve useful card widths")
    func layoutWindowBounds() {
        let defaultMetrics = DashboardLayoutMetrics(
            width: DashboardLayoutMetrics.defaultWindowSize.width
        )
        let minimumMetrics = DashboardLayoutMetrics(
            width: DashboardLayoutMetrics.minimumWindowSize.width
        )

        #expect(DashboardLayoutMetrics.defaultWindowSize == CGSize(width: 620, height: 640))
        #expect(DashboardLayoutMetrics.minimumWindowSize == CGSize(width: 380, height: 480))
        #expect(defaultMetrics.estimatedCardWidth(containerWidth: 620) == 293)
        #expect(minimumMetrics.estimatedCardWidth(containerWidth: 380) == 352)
    }

    @Test("Application entitlements contain no network, microphone, or camera capability")
    func entitlementsRemainLocalOnly() throws {
        let data = try Data(
            contentsOf: packageRoot().appendingPathComponent("OperationsFloater.entitlements")
        )
        let value = try PropertyListSerialization.propertyList(
            from: data,
            options: [],
            format: nil
        )
        let entitlements = try #require(value as? [String: Any])

        #expect(entitlements.count == 2)
        #expect(entitlements["com.apple.security.app-sandbox"] as? Bool == true)
        #expect(
            entitlements["com.apple.security.files.user-selected.read-only"] as? Bool == true
        )
        #expect(entitlements["com.apple.security.network.client"] == nil)
        #expect(entitlements["com.apple.security.device.audio-input"] == nil)
        #expect(entitlements["com.apple.security.device.camera"] == nil)
    }

    private func makeSnapshot(
        queue: [QueueRecord] = [],
        tests: [TestRecord] = [],
        resourceBudget: [ResourceBudgetRecord] = [],
        signals: [SignalRecord] = []
    ) -> DashboardSnapshot {
        DashboardSnapshot(
            schemaVersion: "1.0",
            mode: .sample,
            queue: queue,
            tests: tests,
            resourceBudget: resourceBudget,
            signals: signals
        )
    }

    private func packageRoot() -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
    }
}
