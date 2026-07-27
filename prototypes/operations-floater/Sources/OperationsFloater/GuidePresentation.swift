import CoreGraphics
import Foundation

enum GuideActivity: Equatable, Sendable {
    case attention
    case active
    case ready
    case waiting
    case idle
}

struct GuideCue: Equatable, Sendable {
    let activity: GuideActivity
    let title: String
    let detail: String
}

extension DashboardSnapshot {
    var guideCue: GuideCue {
        let verifiedFailureCount = tests.lazy.filter {
            $0.result == .failed && $0.verification == .verified
        }.count
        let verifiedAttentionCount = signals.lazy.filter {
            $0.state == .attention && $0.verification == .verified
        }.count
        if verifiedFailureCount + verifiedAttentionCount > 0 {
            return GuideCue(
                activity: .attention,
                title: "Verified attention needed",
                detail: countDescription(
                    verifiedFailureCount + verifiedAttentionCount,
                    singular: "verified item needs a decision.",
                    plural: "verified items need a decision."
                )
            )
        }

        let runningCount = queue.lazy.filter { $0.state == .running }.count
        if runningCount > 0 {
            return GuideCue(
                activity: .active,
                title: "Active lane moving",
                detail: countDescription(
                    runningCount,
                    singular: "item is currently in the running lane.",
                    plural: "items are currently in the running lane."
                )
            )
        }

        let readyCount = queue.lazy.filter {
            $0.state == .ready || $0.state == .queued
        }.count
        if readyCount > 0 {
            return GuideCue(
                activity: .ready,
                title: "Next work is staged",
                detail: countDescription(
                    readyCount,
                    singular: "item can keep the queue moving.",
                    plural: "items can keep the queue moving."
                )
            )
        }

        let waitingCount = queue.lazy.filter { $0.state == .waiting }.count
        if waitingCount > 0 {
            return GuideCue(
                activity: .waiting,
                title: "Queue is waiting",
                detail: countDescription(
                    waitingCount,
                    singular: "item is waiting for a dependency.",
                    plural: "items are waiting for dependencies."
                )
            )
        }

        return GuideCue(
            activity: .idle,
            title: "Queue is clear",
            detail: "No operational work is currently supplied."
        )
    }

    private func countDescription(
        _ count: Int,
        singular: String,
        plural: String
    ) -> String {
        "\(count) \(count == 1 ? singular : plural)"
    }
}

struct GuideMotionFrame: Equatable, Sendable {
    let bob: Double
    let eyeScale: Double
    let wave: Double
    let pulse: Double

    static let still = GuideMotionFrame(
        bob: 0,
        eyeScale: 1,
        wave: 0,
        pulse: 1
    )
}

enum GuideMotionSampler {
    static func frame(
        at time: TimeInterval,
        activity: GuideActivity,
        reduceMotion: Bool
    ) -> GuideMotionFrame {
        guard !reduceMotion else { return .still }

        let nonnegativeTime = max(0, time)
        let parameters = parameters(for: activity)
        let blinkPhase = nonnegativeTime.truncatingRemainder(dividingBy: 4)
        return GuideMotionFrame(
            bob: sin(nonnegativeTime * parameters.speed) * parameters.amplitude,
            eyeScale: (3.82...3.96).contains(blinkPhase) ? 0.14 : 1,
            wave: sin(nonnegativeTime * parameters.speed * 1.08) * parameters.wave,
            pulse: 1 + sin(nonnegativeTime * parameters.speed * 0.72) * parameters.pulse
        )
    }

    private static func parameters(
        for activity: GuideActivity
    ) -> (speed: Double, amplitude: Double, wave: Double, pulse: Double) {
        switch activity {
        case .attention:
            (3.0, 3.8, 14, 0.05)
        case .active:
            (2.3, 3.1, 11, 0.04)
        case .ready:
            (1.9, 2.5, 8, 0.035)
        case .waiting:
            (1.5, 1.9, 5, 0.025)
        case .idle:
            (1.2, 1.4, 3, 0.018)
        }
    }
}

enum DashboardLayoutDensity: Equatable, Sendable {
    case compact
    case dense
}

struct DashboardLayoutMetrics: Equatable, Sendable {
    static let defaultWindowSize = CGSize(width: 620, height: 640)
    static let minimumWindowSize = CGSize(width: 380, height: 480)
    static let denseBreakpoint: CGFloat = 560

    let density: DashboardLayoutDensity
    let columnCount: Int
    let contentPadding: CGFloat
    let sectionSpacing: CGFloat
    let recordPadding: CGFloat
    let guideSize: CGFloat

    init(width: CGFloat) {
        if width >= Self.denseBreakpoint {
            density = .dense
            columnCount = 2
            contentPadding = 12
            sectionSpacing = 10
            recordPadding = 9
            guideSize = 74
        } else {
            density = .compact
            columnCount = 1
            contentPadding = 14
            sectionSpacing = 12
            recordPadding = 10
            guideSize = 68
        }
    }

    func estimatedCardWidth(containerWidth: CGFloat) -> CGFloat {
        let available = max(0, containerWidth - contentPadding * 2)
        let totalSpacing = sectionSpacing * CGFloat(max(0, columnCount - 1))
        return max(0, (available - totalSpacing) / CGFloat(columnCount))
    }
}
