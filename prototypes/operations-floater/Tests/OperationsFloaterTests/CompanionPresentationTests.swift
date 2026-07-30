import Foundation
import Testing
@testable import OperationsFloater

@Suite("Companion presentation")
struct CompanionPresentationTests {

    // MARK: - Base mood mapping

    @Test("Base mood mirrors the guide activity for every canonical state")
    func baseMoodMirrorsGuide() {
        #expect(mood(for: snapshot()) == .sleeping)
        #expect(mood(for: snapshot(queue: [item("Q", .running)])) == .focused)
        #expect(mood(for: snapshot(queue: [item("Q", .queued)])) == .staged)
        #expect(mood(for: snapshot(queue: [item("Q", .ready)])) == .staged)
        #expect(mood(for: snapshot(queue: [item("Q", .waiting)])) == .waiting)
    }

    @Test("A non-empty but calm snapshot is idle rather than asleep")
    func calmSnapshotIsIdle() {
        let calm = snapshot(
            tests: [
                TestRecord(
                    id: "T1",
                    title: "Check",
                    detail: "Generic record.",
                    result: .passed,
                    exposure: .sanitized,
                    verification: .verified
                )
            ]
        )

        #expect(calm.isOperationallyEmpty == false)
        #expect(mood(for: calm) == .idle)
    }

    @Test("Verified failures and attention signals make the companion concerned")
    func verifiedTroubleIsConcerned() {
        let failing = snapshot(
            queue: [item("Q", .running)],
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

        #expect(mood(for: failing) == .concerned)
    }

    @Test("A pending owner decision forces concern even while lanes run")
    func receiptAttentionForcesConcern() {
        let running = snapshot(queue: [item("Q", .running)])

        #expect(
            CompanionMood.baseMood(for: running, receiptNeedsAttention: true) == .concerned
        )
        #expect(
            CompanionMood.baseMood(for: running, receiptNeedsAttention: false) == .focused
        )
    }

    // MARK: - Celebration transient

    @Test("Reaching the finished lane triggers a bounded celebration")
    func finishingWorkCelebrates() {
        let before = CompanionReducer.reduce(
            .initial,
            snapshot: snapshot(queue: [item("A", .running)]),
            now: 100
        )
        #expect(before.mood(at: 100) == .focused)

        let after = CompanionReducer.reduce(
            before,
            snapshot: snapshot(queue: [item("A", .ready)]),
            now: 101
        )

        #expect(after.mood(at: 101) == .celebrating)
        #expect(after.mood(at: 101 + CompanionReducer.celebrationDuration - 0.01) == .celebrating)
        #expect(after.mood(at: 101 + CompanionReducer.celebrationDuration) == .staged)
    }

    @Test("Pre-existing finished work on first ingest does not celebrate")
    func baselineDoesNotCelebrate() {
        let seeded = CompanionReducer.reduce(
            .initial,
            snapshot: snapshot(queue: [item("A", .ready), item("B", .ready)]),
            now: 10
        )

        #expect(seeded.hasBaseline)
        #expect(seeded.mood(at: 10) == .staged)
    }

    @Test("A concern cancels any in-flight celebration")
    func concernOverridesCelebration() {
        let celebrating = CompanionReducer.reduce(
            CompanionReducer.reduce(
                .initial,
                snapshot: snapshot(queue: [item("A", .running)]),
                now: 0
            ),
            snapshot: snapshot(queue: [item("A", .ready)]),
            now: 1
        )
        #expect(celebrating.mood(at: 1) == .celebrating)

        let interrupted = CompanionReducer.reduce(
            celebrating,
            snapshot: snapshot(
                queue: [item("A", .ready)],
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
            ),
            now: 2
        )

        #expect(interrupted.mood(at: 2) == .concerned)
        #expect(interrupted.celebrationUntil == nil)
    }

    @Test("Finishing more work while already celebrating extends the celebration")
    func additionalCompletionExtendsCelebration() {
        let first = CompanionReducer.reduce(
            CompanionReducer.reduce(
                .initial,
                snapshot: snapshot(queue: [item("A", .running), item("B", .running)]),
                now: 0
            ),
            snapshot: snapshot(queue: [item("A", .ready), item("B", .running)]),
            now: 1
        )
        let second = CompanionReducer.reduce(
            first,
            snapshot: snapshot(queue: [item("A", .ready), item("B", .ready)]),
            now: 4
        )

        #expect(second.mood(at: 4) == .celebrating)
        // The window is measured from the most recent completion, not the first.
        #expect(second.mood(at: 1 + CompanionReducer.celebrationDuration) == .celebrating)
        #expect(second.mood(at: 4 + CompanionReducer.celebrationDuration) == .staged)
    }

    // MARK: - Poses

    @Test("Every mood resolves to a self-consistent pose")
    func posesAreConsistent() {
        for mood in CompanionMood.allCases {
            let pose = CompanionPose.pose(for: mood)
            #expect(pose.mood == mood)
            #expect((0...1).contains(pose.eyeOpenness))
            #expect((0...1).contains(pose.blush))
            #expect((0...1).contains(pose.tailEnergy))
        }

        #expect(CompanionPose.pose(for: .sleeping).sleeping)
        #expect(CompanionPose.pose(for: .celebrating).happyEyes)
        #expect(CompanionPose.pose(for: .celebrating).sparkles)
        #expect(CompanionPose.pose(for: .concerned).mouth == .frown)
        #expect(CompanionPose.pose(for: .concerned).browAngle > 0)
        // Perked ears when focused, drooped when concerned.
        #expect(CompanionPose.pose(for: .focused).earLift > 0)
        #expect(CompanionPose.pose(for: .concerned).earLift < 0)
    }

    // MARK: - Motion

    @Test("Motion frames are deterministic and bounded")
    func motionIsDeterministicAndBounded() {
        let first = CompanionMotionSampler.frame(at: 7.5, mood: .focused, reduceMotion: false)
        let second = CompanionMotionSampler.frame(at: 7.5, mood: .focused, reduceMotion: false)

        #expect(first == second)
        #expect(first != .still)
        #expect((-1...1).contains(first.breath))
        #expect((0...1).contains(first.blink))
        #expect((-1...1).contains(first.tailSway))
        #expect((0...1).contains(first.hop))
        #expect((0...1).contains(first.sparklePhase))
    }

    @Test("Reduce Motion produces a fully stable frame for every mood")
    func reduceMotionIsStable() {
        for mood in CompanionMood.allCases {
            #expect(
                CompanionMotionSampler.frame(at: 12_345.6, mood: mood, reduceMotion: true) == .still
            )
        }
        #expect(CompanionMotionFrame.still.blink == 1)
        #expect(CompanionMotionFrame.still.hop == 0)
    }

    @Test("Blink closes briefly and only celebration hops")
    func blinkAndHopBehavior() {
        let open = CompanionMotionSampler.frame(at: 1.0, mood: .idle, reduceMotion: false)
        let closing = CompanionMotionSampler.frame(at: 3.9, mood: .idle, reduceMotion: false)
        #expect(open.blink == 1)
        #expect(closing.blink < 0.2)

        #expect(CompanionMotionSampler.frame(at: 1.0, mood: .idle, reduceMotion: false).hop == 0)
        // Celebration hop is non-zero somewhere in its cycle.
        let hops = stride(from: 0.0, through: 1.0, by: 0.05).map {
            CompanionMotionSampler.frame(at: $0, mood: .celebrating, reduceMotion: false).hop
        }
        #expect(hops.contains { $0 > 0.3 })
    }

    // MARK: - Chatter

    @Test("Chatter reflects canonical lane counts with correct pluralization")
    func chatterReflectsCounts() {
        #expect(
            CompanionChatter.line(
                for: .focused,
                snapshot: snapshot(queue: [item("A", .running)])
            ) == "On it — one lane running."
        )
        #expect(
            CompanionChatter.line(
                for: .focused,
                snapshot: snapshot(queue: [item("A", .running), item("B", .running)])
            ) == "On it — 2 lanes running."
        )
        #expect(
            CompanionChatter.line(
                for: .celebrating,
                snapshot: snapshot(queue: [item("A", .ready)])
            ) == "Nice! One lane just wrapped."
        )
        #expect(
            CompanionChatter.line(for: .concerned, snapshot: snapshot())
                == "Something needs your eyes."
        )
        #expect(
            CompanionChatter.line(for: .sleeping, snapshot: snapshot())
                == "All quiet. I'll nap right here."
        )
    }

    // MARK: - Fixtures

    private func mood(for snapshot: DashboardSnapshot) -> CompanionMood {
        CompanionMood.baseMood(for: snapshot, receiptNeedsAttention: false)
    }

    private func item(_ id: String, _ state: QueueRecord.State) -> QueueRecord {
        QueueRecord(
            id: id,
            title: "Example",
            detail: "Generic record.",
            state: state,
            exposure: .sanitized,
            verification: .estimated
        )
    }

    private func snapshot(
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
}
