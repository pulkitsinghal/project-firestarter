import AppKit
import SwiftUI

// MARK: - Accent → color

extension CompanionAccent {
    /// The primary body color.
    var base: Color {
        switch self {
        case .ember: Color(red: 1.0, green: 0.56, blue: 0.24)
        case .sky: Color(red: 0.35, green: 0.66, blue: 0.98)
        case .mint: Color(red: 0.34, green: 0.82, blue: 0.6)
        case .amber: Color(red: 0.98, green: 0.74, blue: 0.28)
        case .rose: Color(red: 1.0, green: 0.52, blue: 0.64)
        case .coral: Color(red: 0.98, green: 0.46, blue: 0.4)
        case .slate: Color(red: 0.62, green: 0.68, blue: 0.78)
        }
    }

    /// A darker variant for outlines and depth.
    var deep: Color {
        switch self {
        case .ember: Color(red: 0.86, green: 0.34, blue: 0.12)
        case .sky: Color(red: 0.16, green: 0.4, blue: 0.8)
        case .mint: Color(red: 0.1, green: 0.56, blue: 0.42)
        case .amber: Color(red: 0.8, green: 0.54, blue: 0.12)
        case .rose: Color(red: 0.86, green: 0.28, blue: 0.46)
        case .coral: Color(red: 0.82, green: 0.26, blue: 0.24)
        case .slate: Color(red: 0.38, green: 0.44, blue: 0.56)
        }
    }

    /// A pale variant for the belly, inner ears, and gradient highlight.
    var pale: Color {
        switch self {
        case .ember: Color(red: 1.0, green: 0.86, blue: 0.7)
        case .sky: Color(red: 0.8, green: 0.9, blue: 1.0)
        case .mint: Color(red: 0.82, green: 0.97, blue: 0.9)
        case .amber: Color(red: 1.0, green: 0.93, blue: 0.74)
        case .rose: Color(red: 1.0, green: 0.85, blue: 0.9)
        case .coral: Color(red: 1.0, green: 0.83, blue: 0.78)
        case .slate: Color(red: 0.88, green: 0.91, blue: 0.96)
        }
    }
}

// MARK: - Controller

/// Bridges the observable dashboard snapshot into companion state. The effective
/// mood is always recomputed at render time via ``CompanionState/mood(at:)`` so
/// the celebration transient decays smoothly without an extra timer.
@MainActor
final class CompanionController: ObservableObject {
    @Published private(set) var snapshot: DashboardSnapshot
    @Published private(set) var state: CompanionState
    private var receiptNeedsAttention: Bool

    init(snapshot: DashboardSnapshot = .emptyLocal) {
        self.snapshot = snapshot
        self.state = .initial
        self.receiptNeedsAttention = false
    }

    func ingest(
        snapshot: DashboardSnapshot,
        receiptNeedsAttention: Bool,
        now: TimeInterval = Date.timeIntervalSinceReferenceDate
    ) {
        self.snapshot = snapshot
        self.receiptNeedsAttention = receiptNeedsAttention
        state = CompanionReducer.reduce(
            state,
            snapshot: snapshot,
            receiptNeedsAttention: receiptNeedsAttention,
            now: now
        )
    }

    func mood(at time: TimeInterval) -> CompanionMood {
        state.mood(at: time)
    }
}

// MARK: - Character (Canvas)

/// A self-contained, vector-drawn companion. It uses no image asset, camera,
/// microphone, network service, or analytics: every pixel is a deterministic
/// function of `(pose, frame)`.
struct CompanionCharacter: View {
    let pose: CompanionPose
    let frame: CompanionMotionFrame
    var style: CompanionStyle = .pet

    var body: some View {
        Canvas(rendersAsynchronously: false) { context, size in
            switch style {
            case .pet:
                CompanionCharacter.draw(&context, size: size, pose: pose, frame: frame)
            case .human:
                CompanionHumanArt.draw(&context, size: size, pose: pose, frame: frame)
            }
        }
        .accessibilityHidden(true)
    }

    static func draw(
        _ context: inout GraphicsContext,
        size: CGSize,
        pose: CompanionPose,
        frame: CompanionMotionFrame
    ) {
        let s = min(size.width, size.height) / 106
        let ox = (size.width - 100 * s) / 2
        let oy = (size.height - 100 * s) / 2
        func p(_ x: Double, _ y: Double) -> CGPoint {
            CGPoint(x: ox + x * s, y: oy + y * s)
        }
        func len(_ v: Double) -> CGFloat { CGFloat(v) * s }
        func ellipse(cx: Double, cy: Double, rx: Double, ry: Double) -> Path {
            Path(
                ellipseIn: CGRect(
                    x: ox + (cx - rx) * s,
                    y: oy + (cy - ry) * s,
                    width: rx * 2 * s,
                    height: ry * 2 * s
                )
            )
        }
        func sparkle(center c: CGPoint, radius r: CGFloat) -> Path {
            var path = Path()
            let north = CGPoint(x: c.x, y: c.y - r)
            let east = CGPoint(x: c.x + r, y: c.y)
            let south = CGPoint(x: c.x, y: c.y + r)
            let west = CGPoint(x: c.x - r, y: c.y)
            path.move(to: north)
            path.addQuadCurve(to: east, control: c)
            path.addQuadCurve(to: south, control: c)
            path.addQuadCurve(to: west, control: c)
            path.addQuadCurve(to: north, control: c)
            path.closeSubpath()
            return path
        }

        let ink = Color(red: 0.17, green: 0.15, blue: 0.22)
        let base = pose.accent.base
        let deep = pose.accent.deep
        let pale = pose.accent.pale
        let outline = StrokeStyle(lineWidth: len(2), lineCap: .round)

        // Vertical bob from breathing plus the celebration hop (y grows downward).
        let dy = frame.breath * 1.1 - frame.hop * 6

        // Ground shadow — stays on the floor, squashing slightly with the breath.
        let shadowSquash = 1 - frame.breath * 0.03 - frame.hop * 0.25
        context.fill(
            ellipse(cx: 50, cy: 91, rx: 24 * max(0.4, shadowSquash), ry: 4.5),
            with: .color(.black.opacity(0.16))
        )

        // Tail (behind the body), swaying with the pose energy.
        let sway = frame.tailSway * pose.tailEnergy
        var tail = Path()
        tail.move(to: p(70, 66 + dy))
        tail.addQuadCurve(
            to: p(90 + sway * 9, 58 + dy - abs(sway) * 4),
            control: p(88, 74 + dy + sway * 3)
        )
        tail.addQuadCurve(to: p(72, 77 + dy), control: p(86, 82 + dy + sway * 3))
        tail.closeSubpath()
        context.fill(tail, with: .color(base))
        context.fill(
            ellipse(cx: 89 + sway * 9, cy: 58 + dy - abs(sway) * 4, rx: 4.5, ry: 4.5),
            with: .color(pale)
        )

        // Feet peeking out beneath the body.
        for footX in [40.0, 60.0] {
            context.fill(ellipse(cx: footX, cy: 87 + dy, rx: 7, ry: 4.5), with: .color(deep.opacity(0.85)))
        }

        // Body.
        let body = ellipse(cx: 50, cy: 59 + dy, rx: 29, ry: 29)
        context.fill(
            body,
            with: .linearGradient(
                Gradient(colors: [pale, base]),
                startPoint: p(50, 30 + dy),
                endPoint: p(50, 88 + dy)
            )
        )
        context.stroke(body, with: .color(deep.opacity(0.35)), lineWidth: len(1.1))

        // Ears (perk up or droop with the pose; small twitch on top).
        let lift = pose.earLift + frame.earTwitch * 3
        let earTipY = 12 - lift * 0.5 + dy
        func ear(baseA: (Double, Double), baseB: (Double, Double), tipX: Double) {
            var shell = Path()
            shell.move(to: p(baseA.0, baseA.1 + dy))
            shell.addLine(to: p(baseB.0, baseB.1 + dy))
            shell.addLine(to: p(tipX, earTipY))
            shell.closeSubpath()
            context.fill(shell, with: .color(base))
            context.stroke(shell, with: .color(deep.opacity(0.35)), lineWidth: len(1))
            let midX = (baseA.0 + baseB.0) / 2
            let midY = (baseA.1 + baseB.1) / 2 + dy
            var inner = Path()
            inner.move(to: p(midX - 3, midY - 1))
            inner.addLine(to: p(midX + 3, midY - 1))
            inner.addLine(
                to: CGPoint(
                    x: p(midX, midY).x + (p(tipX, earTipY).x - p(midX, midY).x) * 0.62,
                    y: p(midX, midY).y + (p(tipX, earTipY).y - p(midX, midY).y) * 0.62
                )
            )
            inner.closeSubpath()
            context.fill(inner, with: .color(pale.opacity(0.95)))
        }
        ear(baseA: (24, 40), baseB: (38, 36), tipX: 30 - lift * 0.32)
        ear(baseA: (62, 36), baseB: (76, 40), tipX: 70 + lift * 0.32)

        // Belly.
        context.fill(ellipse(cx: 50, cy: 66 + dy, rx: 17, ry: 19), with: .color(pale.opacity(0.92)))

        // Cheeks / blush.
        if pose.blush > 0 {
            for cheekX in [30.0, 70.0] {
                context.fill(
                    ellipse(cx: cheekX, cy: 63 + dy, rx: 5, ry: 3.4),
                    with: .color(Color(red: 1, green: 0.5, blue: 0.56).opacity(0.55 * pose.blush))
                )
            }
        }

        // Eyes.
        let eyeXs = [37.0, 63.0]
        if pose.sleeping {
            for eyeX in eyeXs {
                var arc = Path()
                arc.move(to: p(eyeX - 5, 56 + dy))
                arc.addQuadCurve(to: p(eyeX + 5, 56 + dy), control: p(eyeX, 59.5 + dy))
                context.stroke(arc, with: .color(ink), style: outline)
            }
        } else if pose.happyEyes {
            for eyeX in eyeXs {
                var arc = Path()
                arc.move(to: p(eyeX - 5, 57 + dy))
                arc.addQuadCurve(to: p(eyeX + 5, 57 + dy), control: p(eyeX, 51 + dy))
                context.stroke(arc, with: .color(ink), style: outline)
            }
        } else {
            let open = pose.eyeOpenness * frame.blink
            for eyeX in eyeXs {
                context.fill(ellipse(cx: eyeX, cy: 56 + dy, rx: 4.6, ry: 6 * max(0.06, open)), with: .color(ink))
                if open > 0.5 {
                    context.fill(ellipse(cx: eyeX - 1.4, cy: 54 + dy, rx: 1.5, ry: 1.6), with: .color(.white.opacity(0.92)))
                }
            }
        }

        // Worried brows.
        if pose.browAngle > 0 {
            let drop = pose.browAngle * 0.12
            var leftBrow = Path()
            leftBrow.move(to: p(31, 47 + dy))
            leftBrow.addLine(to: p(41, 47 + drop + dy))
            var rightBrow = Path()
            rightBrow.move(to: p(69, 47 + dy))
            rightBrow.addLine(to: p(59, 47 + drop + dy))
            context.stroke(leftBrow, with: .color(ink), style: outline)
            context.stroke(rightBrow, with: .color(ink), style: outline)
        }

        // Nose.
        context.fill(ellipse(cx: 50, cy: 60.5 + dy, rx: 2, ry: 1.5), with: .color(ink))

        // Mouth.
        switch pose.mouth {
        case .smile:
            var mouth = Path()
            mouth.move(to: p(45, 64 + dy))
            mouth.addQuadCurve(to: p(55, 64 + dy), control: p(50, 69 + dy))
            context.stroke(mouth, with: .color(ink), style: outline)
        case .flat:
            var mouth = Path()
            mouth.move(to: p(46, 65.5 + dy))
            mouth.addLine(to: p(54, 65.5 + dy))
            context.stroke(mouth, with: .color(ink), style: outline)
        case .frown:
            var mouth = Path()
            mouth.move(to: p(45, 68 + dy))
            mouth.addQuadCurve(to: p(55, 68 + dy), control: p(50, 63 + dy))
            context.stroke(mouth, with: .color(ink), style: outline)
        case .grin:
            var mouth = Path()
            mouth.move(to: p(44, 64 + dy))
            mouth.addQuadCurve(to: p(56, 64 + dy), control: p(50, 66 + dy))
            mouth.addQuadCurve(to: p(44, 64 + dy), control: p(50, 74 + dy))
            mouth.closeSubpath()
            context.fill(mouth, with: .color(ink))
            context.fill(
                ellipse(cx: 50, cy: 70 + dy, rx: 3.4, ry: 2.4),
                with: .color(Color(red: 1, green: 0.5, blue: 0.55))
            )
        }

        // Sparkles for celebration.
        if pose.sparkles {
            let spots: [(Double, Double, Double)] = [
                (16, 18, 4.2), (86, 24, 3.6), (50, 3, 3.2), (82, 58, 3.4), (14, 54, 2.9),
            ]
            for (sx, sy, sr) in spots {
                let twinkle = 0.35 + 0.65 * abs(sin((frame.sparklePhase + sx * 0.013) * .pi * 2))
                context.fill(
                    sparkle(center: p(sx, sy + dy * 0.3), radius: len(sr * twinkle)),
                    with: .color(.white.opacity(0.85))
                )
            }
        }

        // Sleepy "z z z".
        if pose.sleeping {
            let zs: [(Double, Double, Double)] = [(70, 22, 8), (78, 13, 10), (87, 3, 12)]
            for (zx, zy, fontSize) in zs {
                context.draw(
                    Text("z")
                        .font(.system(size: max(6, len(fontSize)), weight: .bold, design: .rounded))
                        .foregroundStyle(ink.opacity(0.55)),
                    at: p(zx, zy + dy)
                )
            }
        }
    }
}

// MARK: - Speech bubble

private struct CompanionBubble: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.caption2.weight(.medium))
            .foregroundStyle(.primary)
            .multilineTextAlignment(.leading)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .frame(maxWidth: 172, alignment: .leading)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
            .overlay(
                RoundedRectangle(cornerRadius: 12)
                    .stroke(.white.opacity(0.14), lineWidth: 1)
            )
            .shadow(color: .black.opacity(0.14), radius: 5, y: 2)
    }
}

// MARK: - Live corner overlay

/// The dismissible corner companion. When present it shows a status bubble above
/// an animated character; when dismissed it collapses to a small wake button.
struct CompanionView: View {
    @ObservedObject var controller: CompanionController
    @Binding var dismissed: Bool
    var style: CompanionStyle = .pet
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var isHovering = false

    private let characterSize: CGFloat = 82
    private var name: String { style.companionName }

    var body: some View {
        Group {
            if dismissed {
                wakeButton
            } else {
                companion
            }
        }
        .animation(.spring(response: 0.42, dampingFraction: 0.72), value: dismissed)
    }

    private var companion: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30.0, paused: reduceMotion)) { timeline in
            let now = timeline.date.timeIntervalSinceReferenceDate
            let mood = controller.mood(at: now)
            let pose = CompanionPose.pose(for: mood)
            let frame = CompanionMotionSampler.frame(
                at: now,
                mood: mood,
                reduceMotion: reduceMotion
            )
            let line = CompanionChatter.line(for: mood, snapshot: controller.snapshot)

            VStack(alignment: .trailing, spacing: 3) {
                CompanionBubble(text: line)
                ZStack(alignment: .topTrailing) {
                    CompanionCharacter(pose: pose, frame: frame, style: style)
                        .frame(width: characterSize, height: characterSize)
                    if isHovering || reduceMotion {
                        dismissButton
                    }
                }
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("\(name) companion: \(line)")
        }
        .onHover { isHovering = $0 }
        .transition(.scale(scale: 0.6, anchor: .bottomTrailing).combined(with: .opacity))
    }

    private var dismissButton: some View {
        Button {
            dismissed = true
        } label: {
            Image(systemName: "xmark.circle.fill")
                .font(.system(size: 15))
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(.secondary)
                .background(Circle().fill(.background).padding(2))
        }
        .buttonStyle(.plain)
        .help("Hide \(name)")
        .accessibilityLabel("Hide \(name) companion")
        .offset(x: 5, y: -3)
    }

    private var wakeButton: some View {
        Button {
            dismissed = false
        } label: {
            CompanionCharacter(pose: .pose(for: .idle), frame: .still, style: style)
                .frame(width: 30, height: 30)
                .padding(6)
                .background(.regularMaterial, in: Circle())
                .overlay(Circle().stroke(.white.opacity(0.14), lineWidth: 1))
                .shadow(color: .black.opacity(0.14), radius: 4, y: 2)
        }
        .buttonStyle(.plain)
        .help("Show \(name)")
        .accessibilityLabel("Show \(name) companion")
        .transition(.scale.combined(with: .opacity))
    }
}

// MARK: - Gallery & headless preview

/// A static grid of every mood, used by the Xcode preview and the headless PNG
/// renderer. It draws each pose at one deterministic animation frame.
struct CompanionGalleryView: View {
    var style: CompanionStyle = .pet

    private let previewTime: TimeInterval = 0.72

    private let columns = [
        GridItem(.adaptive(minimum: 150), spacing: 14)
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text("\(style.companionName) · operations companion")
                    .font(.headline)
                Text("Mood is a deterministic function of the canonical dashboard snapshot.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            LazyVGrid(columns: columns, spacing: 14) {
                ForEach(CompanionMood.allCases, id: \.self) { mood in
                    moodCard(mood)
                }
            }
        }
        .padding(18)
    }

    private func moodCard(_ mood: CompanionMood) -> some View {
        let pose = CompanionPose.pose(for: mood)
        let frame = CompanionMotionSampler.frame(at: previewTime, mood: mood, reduceMotion: false)
        return VStack(spacing: 6) {
            CompanionCharacter(pose: pose, frame: frame, style: style)
                .frame(width: 84, height: 84)
            Text(mood.rawValue.capitalized)
                .font(.caption.weight(.semibold))
            Text(CompanionChatter.line(for: mood, snapshot: Self.sampleSnapshot(for: mood)))
                .font(.system(size: 9))
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .lineLimit(2)
                .frame(height: 24)
        }
        .frame(maxWidth: .infinity)
        .padding(10)
        .background(.quaternary, in: RoundedRectangle(cornerRadius: 12))
    }

    /// Synthesizes a snapshot whose lane counts make each mood's chatter read
    /// naturally in the gallery.
    static func sampleSnapshot(for mood: CompanionMood) -> DashboardSnapshot {
        func queueItem(_ id: String, _ state: QueueRecord.State) -> QueueRecord {
            QueueRecord(
                id: id,
                title: "Example",
                detail: "Generic record.",
                state: state,
                exposure: .sanitized,
                verification: .estimated
            )
        }
        let queue: [QueueRecord]
        switch mood {
        case .sleeping:
            queue = []
        case .idle:
            queue = []
        case .waiting:
            queue = [queueItem("A", .waiting), queueItem("B", .waiting)]
        case .staged:
            queue = [queueItem("A", .queued), queueItem("B", .ready), queueItem("C", .ready)]
        case .focused:
            queue = [queueItem("A", .running), queueItem("B", .running)]
        case .celebrating:
            queue = [queueItem("A", .ready), queueItem("B", .ready)]
        case .concerned:
            queue = [queueItem("A", .running)]
        }
        return DashboardSnapshot(
            schemaVersion: "1.0",
            mode: mood == .sleeping ? .local : .sample,
            queue: queue,
            tests: [],
            resourceBudget: [],
            signals: []
        )
    }
}

/// Renders the mood gallery to a PNG without a visible window, so a preview
/// artifact can be produced headlessly for review.
enum CompanionPreviewRenderer {
    static let argument = "--render-companion-preview"
    /// Optional style selector for the headless render; defaults to `.pet` so the
    /// original `--render-companion-preview <path>` invocation is unchanged.
    static let styleArgument = "--companion-style"

    static func requestedOutputPath(
        arguments: [String] = ProcessInfo.processInfo.arguments
    ) -> String? {
        guard let index = arguments.firstIndex(of: argument),
              index + 1 < arguments.count else {
            return nil
        }
        return arguments[index + 1]
    }

    /// The style requested via `--companion-style <pet|human>`, defaulting to the
    /// pet when absent or unrecognized.
    static func requestedStyle(
        arguments: [String] = ProcessInfo.processInfo.arguments
    ) -> CompanionStyle {
        guard let index = arguments.firstIndex(of: styleArgument),
              index + 1 < arguments.count else {
            return .pet
        }
        return CompanionStyle(rawValue: arguments[index + 1]) ?? .pet
    }

    @MainActor
    static func render(to path: String, style: CompanionStyle = .pet, scale: CGFloat = 2) -> Bool {
        let content = CompanionGalleryView(style: style)
            .frame(width: 660, height: 588)
            .background(Color(red: 0.1, green: 0.11, blue: 0.13))
        let renderer = ImageRenderer(content: content)
        renderer.scale = scale
        guard let cgImage = renderer.cgImage else { return false }
        let rep = NSBitmapImageRep(cgImage: cgImage)
        guard let data = rep.representation(using: .png, properties: [:]) else { return false }
        do {
            try data.write(to: URL(fileURLWithPath: path))
            return true
        } catch {
            return false
        }
    }
}

#if DEBUG
#Preview("Ember companion gallery") {
    CompanionGalleryView(style: .pet)
        .frame(width: 660, height: 588)
}

#Preview("Nova companion gallery") {
    CompanionGalleryView(style: .human)
        .frame(width: 660, height: 588)
}

#Preview("Ember live corner") {
    let controller = CompanionController(snapshot: CompanionGalleryView.sampleSnapshot(for: .focused))
    return CompanionView(controller: controller, dismissed: .constant(false))
        .padding(40)
        .onAppear {
            controller.ingest(
                snapshot: CompanionGalleryView.sampleSnapshot(for: .focused),
                receiptNeedsAttention: false
            )
        }
}
#endif
