import SwiftUI

// MARK: - Human companion ("Nova")

/// A warm, stylized human assistant that expresses the exact same mood/pose/motion
/// state machine as the pet. Every pixel is a deterministic, vector-drawn function
/// of `(pose, frame)`: no image asset, camera, microphone, network, or personal
/// source is involved. The accent theming reused from the state layer colors the
/// hair and clothing, so each mood stays instantly color-readable while the skin
/// keeps a constant, human-warm tone.
///
/// Field reinterpretation (nothing in the state machine changes):
/// - `pose.earLift` → forward lean / posture (perked = leaning in, drooped = withdrawn).
/// - `pose.tailEnergy` × `frame.tailSway` → a subtle live head sway.
/// - `pose.eyeOpenness` × `frame.blink` → eyelid openness; `sleeping`/`happyEyes`
///   override the eyes to closed resting arcs / smiling squints.
/// - `pose.browAngle` → worried inner-brow tilt.
/// - `pose.mouth`, `pose.blush`, `pose.sparkles`, `frame.breath`, `frame.hop`
///   map to mouth shape, cheeks, celebration sparkles, breathing bob, and a hop.
enum CompanionHumanArt {

    // MARK: Palette

    /// Constant, human-warm skin tones (independent of the mood accent).
    private static let skinTop = Color(red: 0.98, green: 0.80, blue: 0.66)
    private static let skinBottom = Color(red: 0.94, green: 0.72, blue: 0.57)
    private static let skinShadow = Color(red: 0.86, green: 0.60, blue: 0.47)
    private static let ink = Color(red: 0.20, green: 0.16, blue: 0.24)
    private static let iris = Color(red: 0.34, green: 0.24, blue: 0.20)
    private static let cheek = Color(red: 0.97, green: 0.48, blue: 0.50)

    // MARK: Draw

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

        let hairMain = pose.accent.deep
        let hairHi = pose.accent.base
        let shirtMain = pose.accent.base
        let shirtDeep = pose.accent.deep
        let shirtPale = pose.accent.pale
        let outline = StrokeStyle(lineWidth: len(1.9), lineCap: .round, lineJoin: .round)

        // Posture. `earLift` becomes a forward lean: perked ears (focused/staged/
        // celebrating) lean in and rise; drooped ears (waiting/concerned/sleeping)
        // withdraw and sink. Breathing bobs the whole bust; the hop lifts it.
        let lean = pose.earLift / 22.0
        let breathDY = frame.breath * 1.0 - frame.hop * 6
        let headDY = breathDY - lean * 2.2
        let shoulderDY = breathDY * 0.5 - lean * 1.4
        let leanIn = max(0, lean)

        // Ground shadow — stays on the floor, squashing gently with breath and hop.
        let shadowSquash = 1 - frame.breath * 0.03 - frame.hop * 0.22
        context.fill(
            ellipse(cx: 50, cy: 95, rx: 26 * max(0.4, shadowSquash), ry: 4.2),
            with: .color(.black.opacity(0.15))
        )

        // Shoulders / upper torso (the clothed bust) — rises slightly when leaning in.
        var shoulders = Path()
        shoulders.move(to: p(15, 100))
        shoulders.addLine(to: p(16, 88 + shoulderDY))
        shoulders.addQuadCurve(
            to: p(38, 76 + shoulderDY),
            control: p(18, 79 + shoulderDY)
        )
        shoulders.addLine(to: p(62, 76 + shoulderDY))
        shoulders.addQuadCurve(
            to: p(84, 88 + shoulderDY),
            control: p(82, 79 + shoulderDY)
        )
        shoulders.addLine(to: p(85, 100))
        shoulders.closeSubpath()
        context.fill(
            shoulders,
            with: .linearGradient(
                Gradient(colors: [shirtMain, shirtDeep]),
                startPoint: p(50, 74 + shoulderDY),
                endPoint: p(50, 100)
            )
        )
        // Soft crew neckline shadow.
        var neckline = Path()
        neckline.move(to: p(41, 77 + shoulderDY))
        neckline.addQuadCurve(
            to: p(59, 77 + shoulderDY),
            control: p(50, 84 + shoulderDY)
        )
        context.stroke(neckline, with: .color(shirtDeep.opacity(0.7)), lineWidth: len(2.4))
        // A faint collar highlight to give the shirt some form.
        context.fill(
            ellipse(cx: 50, cy: 78 + shoulderDY, rx: 7, ry: 2.4),
            with: .color(shirtPale.opacity(0.35))
        )

        // Neck.
        var neck = Path()
        neck.move(to: p(44, 62 + headDY))
        neck.addLine(to: p(56, 62 + headDY))
        neck.addLine(to: p(55, 77 + shoulderDY))
        neck.addLine(to: p(45, 77 + shoulderDY))
        neck.closeSubpath()
        context.fill(neck, with: .color(skinBottom))
        // Under-chin shadow.
        context.fill(
            ellipse(cx: 50, cy: 64 + headDY, rx: 8, ry: 2.6),
            with: .color(skinShadow.opacity(0.55))
        )

        // Everything from here up is the head group: it bobs with `headDY`, sways a
        // touch with the pose energy, tilts to rest when sleeping, and leans in when
        // focused. Drawing into a transformed copy keeps the transform local.
        var head = context
        let pivot = p(50, 66)
        let sway = frame.tailSway * pose.tailEnergy
        let tiltDegrees = pose.sleeping ? -7.0 : sway * 2.0
        let scale = 1 + leanIn * 0.04
        head.translateBy(x: 0, y: len(headDY))
        head.translateBy(x: pivot.x, y: pivot.y)
        head.rotate(by: .degrees(tiltDegrees))
        head.scaleBy(x: scale, y: scale)
        head.translateBy(x: -pivot.x, y: -pivot.y)

        // Hair behind the head — sits a touch high and narrow so the ears and jaw
        // stay visible (reads as hair framing a face, not a helmet).
        head.fill(ellipse(cx: 50, cy: 37, rx: 22.5, ry: 23), with: .color(hairMain))

        // Ears.
        for earX in [28.5, 71.5] {
            head.fill(ellipse(cx: earX, cy: 47, rx: 3.6, ry: 5), with: .color(skinBottom))
            head.fill(ellipse(cx: earX, cy: 47, rx: 1.6, ry: 2.6), with: .color(skinShadow.opacity(0.55)))
        }

        // Face.
        let face = ellipse(cx: 50, cy: 43, rx: 21, ry: 24)
        head.fill(
            face,
            with: .linearGradient(
                Gradient(colors: [skinTop, skinBottom]),
                startPoint: p(50, 20),
                endPoint: p(50, 67)
            )
        )

        // Cheeks — a constant, faint warmth plus the stronger mood blush.
        for cheekX in [35.0, 65.0] {
            head.fill(
                ellipse(cx: cheekX, cy: 51, rx: 4.6, ry: 3.0),
                with: .color(cheek.opacity(0.14 + 0.5 * pose.blush))
            )
        }

        // Front fringe / bangs: an asymmetric side-swept shape with a soft part,
        // temples that dip toward the ears, and a couple of strand highlights so it
        // reads unmistakably as styled hair.
        var fringe = Path()
        fringe.move(to: p(28, 45))                               // left temple, low
        fringe.addQuadCurve(to: p(44, 35), control: p(33, 42))   // rise toward the part
        fringe.addQuadCurve(to: p(60, 39), control: p(52, 32))   // sweep across (part dips)
        fringe.addQuadCurve(to: p(72, 44), control: p(70, 36))   // down to the right temple
        fringe.addQuadCurve(to: p(75, 25), control: p(79, 35))   // up the right side
        fringe.addQuadCurve(to: p(50, 17), control: p(63, 16))   // over the crown
        fringe.addQuadCurve(to: p(25, 26), control: p(35, 16))   // over to the left
        fringe.addQuadCurve(to: p(28, 45), control: p(22, 36))   // down the left side
        fringe.closeSubpath()
        head.fill(fringe, with: .color(hairMain))
        // Side-swept part + strand highlights.
        var sweep = Path()
        sweep.move(to: p(45, 24))
        sweep.addQuadCurve(to: p(66, 34), control: p(54, 24))
        head.stroke(sweep, with: .color(hairHi.opacity(0.6)), lineWidth: len(2.0))
        var strand = Path()
        strand.move(to: p(34, 30))
        strand.addQuadCurve(to: p(45, 38), control: p(36, 36))
        head.stroke(strand, with: .color(hairHi.opacity(0.4)), lineWidth: len(1.3))

        // Brows. Worry (`browAngle`) lifts and knots the inner ends; alertness
        // (lean-in) raises them a touch. Colored to match the hair.
        let browY = 38.0 - leanIn * 1.1
        let innerLift = pose.browAngle * 0.14
        func brow(outer: Double, inner: Double) {
            var path = Path()
            path.move(to: p(outer, browY + 1.4))
            path.addQuadCurve(
                to: p(inner, browY - innerLift),
                control: p((outer + inner) / 2, browY - innerLift - 0.6)
            )
            head.stroke(path, with: .color(hairMain), style: outline)
        }
        brow(outer: 32, inner: 45)
        brow(outer: 68, inner: 55)

        // Eyes.
        let eyeXs = [40.5, 59.5]
        let eyeCY = 46.5
        if pose.sleeping {
            for eyeX in eyeXs { restingArc(&head, at: p(eyeX, eyeCY), curve: 3.2, ink: ink, style: outline) }
        } else if pose.happyEyes {
            for eyeX in eyeXs { smilingArc(&head, at: p(eyeX, eyeCY), lift: 3.6, ink: ink, style: outline) }
        } else {
            let open = max(0.06, pose.eyeOpenness * frame.blink)
            for eyeX in eyeXs {
                // Sclera + iris + pupil + catchlight, vertically scaled by openness.
                let ry = 3.4 * open
                head.fill(ellipse(cx: eyeX, cy: eyeCY, rx: 4.4, ry: ry), with: .color(.white.opacity(0.95)))
                if open > 0.35 {
                    head.fill(ellipse(cx: eyeX, cy: eyeCY, rx: 2.7, ry: min(3.2, ry)), with: .color(iris))
                    head.fill(ellipse(cx: eyeX, cy: eyeCY, rx: 1.4, ry: min(1.8, ry)), with: .color(ink))
                    head.fill(ellipse(cx: eyeX - 1.0, cy: eyeCY - 1.1, rx: 0.9, ry: 0.9), with: .color(.white.opacity(0.95)))
                }
                // Upper lash line for definition.
                var lash = Path()
                lash.move(to: p(eyeX - 4.6, eyeCY - ry - 0.2))
                lash.addQuadCurve(to: p(eyeX + 4.6, eyeCY - ry - 0.2), control: p(eyeX, eyeCY - ry - 1.6))
                head.stroke(lash, with: .color(ink), lineWidth: len(1.3))
            }
        }

        // Nose — a soft, minimal shadow with a gentle tip.
        var nose = Path()
        nose.move(to: p(48.4, 49))
        nose.addQuadCurve(to: p(51.6, 53), control: p(48.2, 52.6))
        head.stroke(nose, with: .color(skinShadow.opacity(0.7)), style: StrokeStyle(lineWidth: len(1.4), lineCap: .round))

        // Mouth.
        drawMouth(&head, mouth: pose.mouth, p: p, len: len, ink: ink)

        // Celebration sparkles orbit the head in the untransformed context so they
        // twinkle steadily regardless of the head tilt.
        if pose.sparkles {
            let spots: [(Double, Double, Double)] = [
                (16, 20, 4.0), (85, 24, 3.6), (50, 6, 3.2), (82, 52, 3.2), (17, 50, 2.8),
            ]
            for (sx, sy, sr) in spots {
                let twinkle = 0.35 + 0.65 * abs(sin((frame.sparklePhase + sx * 0.013) * .pi * 2))
                context.fill(
                    sparkle(center: p(sx, sy + headDY * 0.4), radius: len(sr * twinkle)),
                    with: .color(.white.opacity(0.85))
                )
            }
        }

        // Sleepy "z z z".
        if pose.sleeping {
            let zs: [(Double, Double, Double)] = [(72, 26, 8), (80, 17, 10), (89, 7, 12)]
            for (zx, zy, fontSize) in zs {
                context.draw(
                    Text("z")
                        .font(.system(size: max(6, len(fontSize)), weight: .bold, design: .rounded))
                        .foregroundStyle(ink.opacity(0.5)),
                    at: p(zx, zy + headDY)
                )
            }
        }
    }

    // MARK: Feature helpers

    private static func restingArc(
        _ context: inout GraphicsContext,
        at center: CGPoint,
        curve: CGFloat,
        ink: Color,
        style: StrokeStyle
    ) {
        var arc = Path()
        arc.move(to: CGPoint(x: center.x - 5 * curve / 3.2, y: center.y))
        arc.addQuadCurve(
            to: CGPoint(x: center.x + 5 * curve / 3.2, y: center.y),
            control: CGPoint(x: center.x, y: center.y + curve)
        )
        context.stroke(arc, with: .color(ink), style: style)
    }

    private static func smilingArc(
        _ context: inout GraphicsContext,
        at center: CGPoint,
        lift: CGFloat,
        ink: Color,
        style: StrokeStyle
    ) {
        var arc = Path()
        arc.move(to: CGPoint(x: center.x - 5, y: center.y + 1))
        arc.addQuadCurve(
            to: CGPoint(x: center.x + 5, y: center.y + 1),
            control: CGPoint(x: center.x, y: center.y - lift)
        )
        context.stroke(arc, with: .color(ink), style: style)
    }

    private static func drawMouth(
        _ context: inout GraphicsContext,
        mouth: CompanionMouth,
        p: (Double, Double) -> CGPoint,
        len: (Double) -> CGFloat,
        ink: Color
    ) {
        let style = StrokeStyle(lineWidth: len(1.9), lineCap: .round, lineJoin: .round)
        switch mouth {
        case .smile:
            var path = Path()
            path.move(to: p(44, 57))
            path.addQuadCurve(to: p(56, 57), control: p(50, 61.5))
            context.stroke(path, with: .color(ink), style: style)
        case .flat:
            var path = Path()
            path.move(to: p(45.5, 58))
            path.addQuadCurve(to: p(54.5, 58), control: p(50, 58.6))
            context.stroke(path, with: .color(ink), style: style)
        case .frown:
            var path = Path()
            path.move(to: p(45, 60))
            path.addQuadCurve(to: p(55, 60), control: p(50, 55.5))
            context.stroke(path, with: .color(ink), style: style)
        case .grin:
            // Open, warm smile: a filled mouth with a lip line and a tongue hint.
            var path = Path()
            path.move(to: p(43, 56.5))
            path.addQuadCurve(to: p(57, 56.5), control: p(50, 58))
            path.addQuadCurve(to: p(43, 56.5), control: p(50, 65))
            path.closeSubpath()
            context.fill(path, with: .color(ink))
            context.fill(
                Path(ellipseIn: CGRect(
                    x: p(46, 60).x, y: p(46, 60).y,
                    width: p(54, 63.5).x - p(46, 60).x,
                    height: p(54, 63.5).y - p(46, 60).y
                )),
                with: .color(cheek)
            )
        }
    }
}
