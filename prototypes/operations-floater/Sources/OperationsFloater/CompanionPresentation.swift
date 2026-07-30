import CoreGraphics
import Foundation

// MARK: - Mood

/// The companion "Ember" expresses the dashboard's operational state as a mood.
///
/// The mood is a deterministic function of the canonical snapshot (via the
/// already-tested ``DashboardSnapshot/guideCue``) plus one time-boxed transient:
/// a short celebration when work newly reaches the finished lane. No mood is
/// derived from any image, camera, microphone, network, or personal source.
enum CompanionMood: String, Equatable, Sendable, CaseIterable {
    /// No operational records at all — the companion naps.
    case sleeping
    /// Records exist but the queue is clear of active work.
    case idle
    /// One or more items are waiting on a dependency.
    case waiting
    /// Next work is staged (ready or queued) with nothing running.
    case staged
    /// One or more lanes are running — the companion perks up.
    case focused
    /// Work just reached the finished lane — a short, happy transient.
    case celebrating
    /// Verified failures/attention or a pending owner decision need eyes.
    case concerned

    /// The stable, snapshot-derived mood before any celebration transient.
    static func baseMood(
        for snapshot: DashboardSnapshot,
        receiptNeedsAttention: Bool
    ) -> CompanionMood {
        if receiptNeedsAttention {
            return .concerned
        }
        switch snapshot.guideCue.activity {
        case .attention:
            return .concerned
        case .active:
            return .focused
        case .ready:
            return .staged
        case .waiting:
            return .waiting
        case .idle:
            return snapshot.isOperationallyEmpty ? .sleeping : .idle
        }
    }
}

extension DashboardSnapshot {
    /// True when the snapshot carries no records in any lane.
    var isOperationallyEmpty: Bool {
        queue.isEmpty && tests.isEmpty && resourceBudget.isEmpty && signals.isEmpty
    }

    /// Count of queue items that have reached the finished (`ready`) lane.
    var readyLaneCount: Int {
        queue.lazy.filter { $0.state == .ready }.count
    }

    /// Count of queue items actively running.
    var runningLaneCount: Int {
        queue.lazy.filter { $0.state == .running }.count
    }

    /// Count of queue items waiting on a dependency.
    var waitingLaneCount: Int {
        queue.lazy.filter { $0.state == .waiting }.count
    }

    /// Count of queue items staged but not yet running (`queued`).
    var queuedLaneCount: Int {
        queue.lazy.filter { $0.state == .queued }.count
    }
}

// MARK: - State machine

/// The persisted companion state. `mood(at:)` folds the celebration transient
/// back into the base mood once it expires, so the effective mood is a pure
/// function of the stored state and the current time.
struct CompanionState: Equatable, Sendable {
    var baseMood: CompanionMood
    var readyLaneCount: Int
    var celebrationUntil: TimeInterval?
    var hasBaseline: Bool

    static let initial = CompanionState(
        baseMood: .sleeping,
        readyLaneCount: 0,
        celebrationUntil: nil,
        hasBaseline: false
    )

    /// The mood to display at `time`. Concern always wins over a celebration;
    /// an expired celebration falls back to the base mood.
    func mood(at time: TimeInterval) -> CompanionMood {
        if baseMood == .concerned {
            return .concerned
        }
        if let celebrationUntil, time < celebrationUntil {
            return .celebrating
        }
        return baseMood
    }

    func isCelebrating(at time: TimeInterval) -> Bool {
        mood(at: time) == .celebrating
    }
}

/// Reduces successive dashboard snapshots into companion state. A celebration is
/// triggered only when the finished-lane count strictly increases relative to
/// the previous baseline, and never while the base mood is concerned.
enum CompanionReducer {
    static let celebrationDuration: TimeInterval = 6

    static func reduce(
        _ previous: CompanionState,
        snapshot: DashboardSnapshot,
        receiptNeedsAttention: Bool = false,
        now: TimeInterval
    ) -> CompanionState {
        let base = CompanionMood.baseMood(
            for: snapshot,
            receiptNeedsAttention: receiptNeedsAttention
        )
        let readyLaneCount = snapshot.readyLaneCount

        var celebrationUntil = previous.celebrationUntil
        if let existing = celebrationUntil, now >= existing {
            celebrationUntil = nil
        }

        let finishedMoreWork =
            previous.hasBaseline && readyLaneCount > previous.readyLaneCount
        if finishedMoreWork && base != .concerned {
            celebrationUntil = now + celebrationDuration
        }
        if base == .concerned {
            celebrationUntil = nil
        }

        return CompanionState(
            baseMood: base,
            readyLaneCount: readyLaneCount,
            celebrationUntil: celebrationUntil,
            hasBaseline: true
        )
    }
}

// MARK: - Pose (static per-mood expression)

/// A named accent so the state layer stays free of any UI type. The view maps
/// each case to a concrete color.
enum CompanionAccent: String, Equatable, Sendable {
    case ember
    case sky
    case mint
    case amber
    case rose
    case coral
    case slate
}

/// The mouth shape for a pose. Kept as a small enum so it is trivial to test.
enum CompanionMouth: String, Equatable, Sendable {
    case smile
    case grin
    case flat
    case frown
}

/// A static, per-mood description of the companion's expression. Everything here
/// is time-invariant; motion is layered separately by ``CompanionMotionFrame``.
struct CompanionPose: Equatable, Sendable {
    let mood: CompanionMood
    /// Ear lift in degrees. Positive perks the ears up; negative droops them.
    let earLift: Double
    /// Baseline eye openness, 0...1, before any blink is applied.
    let eyeOpenness: Double
    /// Draw closed happy arcs instead of round eyes (celebration).
    let happyEyes: Bool
    /// Draw sleeping eyes and a "z z z" cue.
    let sleeping: Bool
    /// Inner-brow tilt in degrees for a worried look.
    let browAngle: Double
    let mouth: CompanionMouth
    /// Cheek blush strength, 0...1.
    let blush: Double
    /// Whether twinkling sparkles orbit the head.
    let sparkles: Bool
    let accent: CompanionAccent
    /// Tail wag energy, 0...1, scaling both amplitude and speed.
    let tailEnergy: Double

    static func pose(for mood: CompanionMood) -> CompanionPose {
        switch mood {
        case .sleeping:
            return CompanionPose(
                mood: mood,
                earLift: -14,
                eyeOpenness: 0,
                happyEyes: false,
                sleeping: true,
                browAngle: 0,
                mouth: .smile,
                blush: 0,
                sparkles: false,
                accent: .slate,
                tailEnergy: 0.08
            )
        case .idle:
            return CompanionPose(
                mood: mood,
                earLift: 6,
                eyeOpenness: 0.9,
                happyEyes: false,
                sleeping: false,
                browAngle: 0,
                mouth: .smile,
                blush: 0,
                sparkles: false,
                accent: .ember,
                tailEnergy: 0.4
            )
        case .waiting:
            return CompanionPose(
                mood: mood,
                earLift: -9,
                eyeOpenness: 0.6,
                happyEyes: false,
                sleeping: false,
                browAngle: 6,
                mouth: .flat,
                blush: 0,
                sparkles: false,
                accent: .amber,
                tailEnergy: 0.22
            )
        case .staged:
            return CompanionPose(
                mood: mood,
                earLift: 12,
                eyeOpenness: 0.95,
                happyEyes: false,
                sleeping: false,
                browAngle: 0,
                mouth: .smile,
                blush: 0,
                sparkles: false,
                accent: .mint,
                tailEnergy: 0.6
            )
        case .focused:
            return CompanionPose(
                mood: mood,
                earLift: 20,
                eyeOpenness: 1,
                happyEyes: false,
                sleeping: false,
                browAngle: 0,
                mouth: .smile,
                blush: 0,
                sparkles: false,
                accent: .sky,
                tailEnergy: 0.85
            )
        case .celebrating:
            return CompanionPose(
                mood: mood,
                earLift: 22,
                eyeOpenness: 1,
                happyEyes: true,
                sleeping: false,
                browAngle: 0,
                mouth: .grin,
                blush: 1,
                sparkles: true,
                accent: .rose,
                tailEnergy: 1
            )
        case .concerned:
            return CompanionPose(
                mood: mood,
                earLift: -12,
                eyeOpenness: 0.95,
                happyEyes: false,
                sleeping: false,
                browAngle: 18,
                mouth: .frown,
                blush: 0,
                sparkles: false,
                accent: .coral,
                tailEnergy: 0.14
            )
        }
    }
}

// MARK: - Motion (time-varying)

/// A single animation frame for the companion. All values are bounded and are a
/// deterministic function of `(time, mood)`. Reduce Motion yields ``still``.
struct CompanionMotionFrame: Equatable, Sendable {
    /// Slow breathing signal, -1...1.
    let breath: Double
    /// Eye-openness multiplier from blinking, 0...1 (1 = fully open).
    let blink: Double
    /// Tail sway, -1...1.
    let tailSway: Double
    /// Small ear twitch, -1...1.
    let earTwitch: Double
    /// Celebration hop height, 0...1.
    let hop: Double
    /// Sparkle twinkle phase, 0...1.
    let sparklePhase: Double

    static let still = CompanionMotionFrame(
        breath: 0,
        blink: 1,
        tailSway: 0,
        earTwitch: 0,
        hop: 0,
        sparklePhase: 0
    )
}

enum CompanionMotionSampler {
    /// The fixed blink cadence. Eyes close briefly near the end of each period.
    static let blinkPeriod: TimeInterval = 4

    static func frame(
        at time: TimeInterval,
        mood: CompanionMood,
        reduceMotion: Bool
    ) -> CompanionMotionFrame {
        guard !reduceMotion else { return .still }

        let t = max(0, time)
        let parameters = parameters(for: mood)

        let breath = sin(t * parameters.breathSpeed)

        // A short, deterministic blink near the end of each period. Sleeping and
        // celebrating moods override the eyes entirely, so their blink value is
        // unused by the view but still defined here for determinism.
        let blinkPhase = t.truncatingRemainder(dividingBy: blinkPeriod)
        let blink = (3.84...3.98).contains(blinkPhase) ? 0.1 : 1

        let tailSway = sin(t * parameters.tailSpeed)
        let earTwitch = sin(t * parameters.tailSpeed * 0.5 + 1.3) * 0.5
        let hop = mood == .celebrating ? abs(sin(t * 6)) : 0
        let sparklePhase = (t * 0.5).truncatingRemainder(dividingBy: 1)

        return CompanionMotionFrame(
            breath: breath,
            blink: blink,
            tailSway: tailSway,
            earTwitch: earTwitch,
            hop: hop,
            sparklePhase: sparklePhase
        )
    }

    private static func parameters(
        for mood: CompanionMood
    ) -> (breathSpeed: Double, tailSpeed: Double) {
        switch mood {
        case .sleeping:
            return (0.9, 0.6)
        case .idle:
            return (1.4, 1.6)
        case .waiting:
            return (1.2, 1.1)
        case .staged:
            return (1.7, 2.4)
        case .focused:
            return (2.1, 3.4)
        case .celebrating:
            return (2.6, 5.0)
        case .concerned:
            return (1.9, 0.9)
        }
    }
}

// MARK: - Chatter (status bubble)

/// Builds the companion's short status line. The text reflects only canonical
/// lane counts, so it is a deterministic function of `(mood, snapshot)`.
enum CompanionChatter {
    static func line(for mood: CompanionMood, snapshot: DashboardSnapshot) -> String {
        switch mood {
        case .sleeping:
            return "All quiet. I'll nap right here."
        case .idle:
            return "Queue's clear — standing by."
        case .waiting:
            let count = snapshot.waitingLaneCount
            return count == 1
                ? "One item's waiting on a dependency."
                : "\(count) items are waiting on dependencies."
        case .staged:
            let count = snapshot.readyLaneCount + snapshot.queuedLaneCount
            return count == 1
                ? "One item's staged and ready to go."
                : "\(count) items staged and ready to go."
        case .focused:
            let count = snapshot.runningLaneCount
            return count == 1
                ? "On it — one lane running."
                : "On it — \(count) lanes running."
        case .celebrating:
            let count = snapshot.readyLaneCount
            return count == 1
                ? "Nice! One lane just wrapped."
                : "Nice! \(count) lanes wrapped up."
        case .concerned:
            return "Something needs your eyes."
        }
    }

    /// A short, human name used in accessibility labels and the wake affordance.
    static let name = "Ember"
}
