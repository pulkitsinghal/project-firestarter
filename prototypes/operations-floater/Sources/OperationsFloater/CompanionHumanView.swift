import SwiftUI

// MARK: - Human companion ("Nova")

/// A small, floating, **holographic full-figure** AI assistant — a Cortana-style
/// projected person rather than a face-and-shoulders bust. She is translucent and
/// softly glowing: an ethereal rim-light traces her edges, an inner core glow lifts
/// from her centerline, faint scanlines and rising motes shimmer across her, and her
/// lower body dissolves into light above a projector footprint.
///
/// Every pixel is a deterministic, vector-drawn function of `(pose, frame)`: no image
/// asset, camera, microphone, network, or personal source is involved. She is driven
/// by the *same* mood/pose/motion state machine as the pet — nothing in that state
/// machine changes. The rendering reinterprets its fields as a full-body performance:
///
/// - `pose.mood` selects the whole-body **stance and arm posture** (idle = relaxed,
///   waiting = hand-on-hip, staged = open presenting gesture, focused = leaning in,
///   celebrating = arms-up bloom, concerned = arms crossed, sleeping = curled/seated).
/// - `pose.tailEnergy` drives the **aura / glow intensity** (celebrating brightest,
///   sleeping & concerned dimmest) so each mood stays instantly readable as light.
/// - `pose.earLift` → forward **lean** (perked = leaning in, drooped = withdrawn).
/// - `pose.accent` tints the entire hologram, keeping every mood color-coded.
/// - `pose.eyeOpenness` × `frame.blink`, `pose.happyEyes`, `pose.sleeping`,
///   `pose.browAngle`, `pose.mouth`, `pose.blush`, `pose.sparkles`, `frame.breath`,
///   `frame.tailSway`, `frame.hop`, `frame.sparklePhase` map to eyelids, expression,
///   cheeks, sparkles, breathing bob, head sway, celebration hop, and shimmer phase.
///
/// Reduce Motion yields ``CompanionMotionFrame/still`` (breath/sway/hop/shimmer all
/// zero, eyes open), so the figure holds a stable, fully static pose per mood.
enum CompanionHumanArt {

    // MARK: Holographic palette (drawing-only tunables)

    /// A luminous, hologram-tinted set of tones derived from a mood accent. These are
    /// pure presentation values — the state layer only hands us the `accent` case.
    private struct Holo {
        let fill: Color     // translucent body light
        let core: Color     // bright inner core / catchlights
        let rim: Color      // crisp edge rim-light
        let glow: Color     // soft aura bloom
        let feature: Color  // eyes / lash lines (reads against the glowing skin)
    }

    private static func holo(for accent: CompanionAccent) -> Holo {
        func c(_ r: Double, _ g: Double, _ b: Double) -> Color {
            Color(red: r, green: g, blue: b)
        }
        switch accent {
        case .ember:
            return Holo(
                fill: c(1.0, 0.60, 0.32), core: c(1.0, 0.87, 0.68),
                rim: c(1.0, 0.79, 0.54), glow: c(1.0, 0.58, 0.28),
                feature: c(0.44, 0.16, 0.10)
            )
        case .sky:
            return Holo(
                fill: c(0.44, 0.74, 1.0), core: c(0.83, 0.95, 1.0),
                rim: c(0.68, 0.90, 1.0), glow: c(0.40, 0.72, 1.0),
                feature: c(0.13, 0.24, 0.44)
            )
        case .mint:
            return Holo(
                fill: c(0.40, 0.90, 0.70), core: c(0.84, 1.0, 0.93),
                rim: c(0.68, 0.98, 0.86), glow: c(0.34, 0.90, 0.68),
                feature: c(0.09, 0.34, 0.26)
            )
        case .amber:
            return Holo(
                fill: c(1.0, 0.81, 0.40), core: c(1.0, 0.96, 0.76),
                rim: c(1.0, 0.90, 0.62), glow: c(1.0, 0.78, 0.34),
                feature: c(0.42, 0.30, 0.08)
            )
        case .rose:
            return Holo(
                fill: c(1.0, 0.56, 0.72), core: c(1.0, 0.88, 0.93),
                rim: c(1.0, 0.80, 0.88), glow: c(1.0, 0.52, 0.70),
                feature: c(0.46, 0.16, 0.28)
            )
        case .coral:
            return Holo(
                fill: c(1.0, 0.52, 0.46), core: c(1.0, 0.84, 0.79),
                rim: c(1.0, 0.76, 0.71), glow: c(1.0, 0.48, 0.42),
                feature: c(0.44, 0.15, 0.13)
            )
        case .slate:
            return Holo(
                fill: c(0.62, 0.74, 0.92), core: c(0.90, 0.95, 1.0),
                rim: c(0.83, 0.90, 1.0), glow: c(0.58, 0.72, 0.92),
                feature: c(0.24, 0.30, 0.42)
            )
        }
    }

    // MARK: Body posture (rendering-only mood → full-figure mapping)

    /// One arm, described by an elbow and a hand in the 100×100 design space. The
    /// shoulder is fixed; the elbow acts as the bend control for a smooth limb curve.
    private struct ArmPose {
        let elbow: (Double, Double)
        let hand: (Double, Double)
    }

    /// A full-body stance for a mood. Everything here is a *drawing* decision; it adds
    /// no state and reads nothing the state machine does not already expose.
    private struct BodyPose {
        let seated: Bool
        let leftArm: ArmPose
        let rightArm: ArmPose
    }

    private static func bodyPose(for mood: CompanionMood) -> BodyPose {
        switch mood {
        case .sleeping:
            // Curled and seated; arms wrap the knees (drawn by the seated routine).
            return BodyPose(
                seated: true,
                leftArm: ArmPose(elbow: (38, 66), hand: (48, 71)),
                rightArm: ArmPose(elbow: (62, 66), hand: (52, 71))
            )
        case .idle:
            // Relaxed contrapposto, arms resting at the sides.
            return BodyPose(
                seated: false,
                leftArm: ArmPose(elbow: (35, 47), hand: (35.5, 58)),
                rightArm: ArmPose(elbow: (65, 47), hand: (64.5, 58))
            )
        case .waiting:
            // Hand on hip (left), the other arm resting — a patient "still waiting".
            return BodyPose(
                seated: false,
                leftArm: ArmPose(elbow: (32, 47), hand: (43, 55)),
                rightArm: ArmPose(elbow: (65, 47), hand: (65, 58))
            )
        case .staged:
            // Open, presenting gesture — one hand lifted outward: "ready when you are".
            return BodyPose(
                seated: false,
                leftArm: ArmPose(elbow: (33, 44), hand: (27, 33)),
                rightArm: ArmPose(elbow: (64, 47), hand: (66, 57))
            )
        case .focused:
            // Leaning in, both hands forward as if working a console.
            return BodyPose(
                seated: false,
                leftArm: ArmPose(elbow: (38, 47), hand: (46, 55)),
                rightArm: ArmPose(elbow: (62, 47), hand: (54, 55))
            )
        case .celebrating:
            // Arms thrown up in a bright V.
            return BodyPose(
                seated: false,
                leftArm: ArmPose(elbow: (33, 35), hand: (26, 20)),
                rightArm: ArmPose(elbow: (67, 35), hand: (74, 20))
            )
        case .concerned:
            // Arms crossed over the chest; withdrawn.
            return BodyPose(
                seated: false,
                leftArm: ArmPose(elbow: (37, 46), hand: (60, 52)),
                rightArm: ArmPose(elbow: (63, 46), hand: (40, 54))
            )
        }
    }

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
        func len(_ v: Double) -> CGFloat { CGFloat(v) * s }

        let tones = holo(for: pose.accent)
        let body = bodyPose(for: pose.mood)
        let seated = body.seated

        // Motion & mood scalars ------------------------------------------------------
        // Aura/glow intensity is driven straight off the state field so celebration
        // blooms and sleep/concern dim, with a floor so every mood still reads.
        let glow = 0.20 + 0.80 * pose.tailEnergy
        let lean = pose.earLift / 22.0                     // forward lean (perked = in)
        let bob = frame.breath * 0.8
        let hop = frame.hop
        let dyAll = bob - hop * 7.0                          // whole-figure vertical
        let sway = frame.tailSway * pose.tailEnergy          // subtle live head sway
        let headSwayX = sway * 1.6
        // Seated (sleeping) drops the head down to rest over the hugged knees; standing
        // moods dip the head in / lift it back with the lean.
        let headExtraY = seated ? 3.0 : lean * 1.3
        let headDrop = seated ? 24.0 : 0.0
        let glowPulse = 1.0 + 0.10 * frame.breath            // gentle holographic pulse

        // Coordinate mappers: T for the grounded body, H for the head/face group.
        func T(_ x: Double, _ y: Double) -> CGPoint {
            CGPoint(x: ox + x * s, y: oy + (y + dyAll) * s)
        }
        func H(_ x: Double, _ y: Double) -> CGPoint {
            CGPoint(x: ox + (x + headSwayX) * s, y: oy + (y + dyAll + headExtraY + headDrop) * s)
        }
        func ellipseT(_ cx: Double, _ cy: Double, _ rx: Double, _ ry: Double) -> Path {
            Path(ellipseIn: CGRect(
                x: T(cx - rx, cy).x, y: T(cx, cy - ry).y,
                width: rx * 2 * s, height: ry * 2 * s
            ))
        }
        func ellipseH(_ cx: Double, _ cy: Double, _ rx: Double, _ ry: Double) -> Path {
            Path(ellipseIn: CGRect(
                x: H(cx - rx, cy).x, y: H(cx, cy - ry).y,
                width: rx * 2 * s, height: ry * 2 * s
            ))
        }
        func limb(_ shoulder: CGPoint, _ elbow: CGPoint, _ hand: CGPoint, width: CGFloat) -> Path {
            var line = Path()
            line.move(to: shoulder)
            line.addQuadCurve(to: hand, control: elbow)
            return line.strokedPath(StrokeStyle(lineWidth: width, lineCap: .round, lineJoin: .round))
        }
        func sparkle(center c: CGPoint, radius r: CGFloat) -> Path {
            var path = Path()
            path.move(to: CGPoint(x: c.x, y: c.y - r))
            path.addQuadCurve(to: CGPoint(x: c.x + r, y: c.y), control: c)
            path.addQuadCurve(to: CGPoint(x: c.x, y: c.y + r), control: c)
            path.addQuadCurve(to: CGPoint(x: c.x - r, y: c.y), control: c)
            path.addQuadCurve(to: CGPoint(x: c.x, y: c.y - r), control: c)
            path.closeSubpath()
            return path
        }

        // 1) Projector footprint — a bright disc of light the figure floats above. ----
        let baseY = seated ? 79.0 : 90.0
        let baseGlow = glow * glowPulse
        do {
            var g = context
            g.blendMode = .plusLighter
            g.fill(
                ellipseT(50, baseY, 22 * (0.7 + 0.5 * baseGlow), 3.4),
                with: .radialGradient(
                    Gradient(colors: [tones.glow.opacity(0.55 * baseGlow), tones.glow.opacity(0)]),
                    center: T(50, baseY), startRadius: 0, endRadius: len(22)
                )
            )
            g.fill(
                ellipseT(50, baseY, 13, 1.1),
                with: .color(tones.rim.opacity(0.7 * baseGlow))
            )
        }

        // 2) Outer aura — a large, soft bloom behind the whole figure. ---------------
        do {
            var aura = context
            aura.blendMode = .plusLighter
            aura.addFilter(.blur(radius: len(5)))
            aura.fill(
                ellipseT(50, 46, 30, 40),
                with: .radialGradient(
                    Gradient(colors: [tones.glow.opacity(0.30 * baseGlow), tones.glow.opacity(0)]),
                    center: T(50, 44), startRadius: 0, endRadius: len(40)
                )
            )
        }

        // Silhouette (union of head, neck, torso, legs/seat, arms). Filled once so the
        // translucency stays even, and reused as a clip for the inner glow & scanlines.
        let sil = Self.silhouette(
            body: body, T: T, H: H, ellipseT: ellipseT, ellipseH: ellipseH, limb: limb
        )

        // 3) Body light — a vertical gradient that fades toward the feet (dissolve). --
        do {
            var g = context
            g.blendMode = .plusLighter
            g.fill(
                sil,
                with: .linearGradient(
                    Gradient(stops: [
                        .init(color: tones.fill.opacity(0.40), location: 0.0),
                        .init(color: tones.fill.opacity(0.34), location: 0.45),
                        .init(color: tones.fill.opacity(0.16), location: 0.78),
                        .init(color: tones.fill.opacity(0.0), location: 1.0),
                    ]),
                    startPoint: T(50, 10), endPoint: T(50, body.seated ? 84 : 92)
                )
            )
        }

        // 4) Inner core glow + scanline shimmer, clipped to the silhouette. -----------
        do {
            var g = context
            g.clip(to: sil)
            g.blendMode = .plusLighter
            // Core: a bright column of light down the centerline.
            g.fill(
                ellipseT(50, 42, 9, 34),
                with: .radialGradient(
                    Gradient(colors: [tones.core.opacity(0.34 * glowPulse), tones.core.opacity(0)]),
                    center: T(50, 40), startRadius: 0, endRadius: len(30)
                )
            )
            // Faint fixed scanlines.
            for y in stride(from: 12.0, through: 86.0, by: 3.0) {
                var line = Path()
                line.move(to: T(20, y))
                line.addLine(to: T(80, y))
                g.stroke(line, with: .color(tones.core.opacity(0.06)), lineWidth: len(0.7))
            }
            // A single brighter scan band that sweeps down for a live shimmer.
            let bandY = 12.0 + frame.sparklePhase * 74.0
            var band = Path()
            band.move(to: T(20, bandY))
            band.addLine(to: T(80, bandY))
            g.stroke(band, with: .color(tones.rim.opacity(0.22)), lineWidth: len(1.6))
        }

        // 5) Hair — a soft crown plus flowing, shoulder-length locks. -----------------
        do {
            var g = context
            g.blendMode = .plusLighter
            // Crown mass, sitting a touch high and dropping behind the neck.
            g.fill(ellipseH(50, 20.5, 9.2, 10.4), with: .color(tones.fill.opacity(0.28)))
            // Long side locks: tapered filled tresses with a bright inner strand, each
            // curling gently inward at the tip and drifting with the sway.
            for sign in [-1.0, 1.0] {
                let tipX = 50 + sign * 7.4 + sway * sign
                var tress = Path()
                tress.move(to: H(50 + sign * 7.6, 14))
                tress.addQuadCurve(to: H(tipX, 40), control: H(50 + sign * 11.4, 25))
                tress.addQuadCurve(to: H(50 + sign * 4.2, 40.5), control: H(50 + sign * 5.6, 41.5))
                tress.addQuadCurve(to: H(50 + sign * 5.2, 15), control: H(50 + sign * 4.6, 25))
                tress.closeSubpath()
                g.fill(tress, with: .color(tones.fill.opacity(0.30)))
                // Bright strand highlight running down the tress.
                var strand = Path()
                strand.move(to: H(50 + sign * 7.2, 15))
                strand.addQuadCurve(to: H(tipX - sign * 0.6, 38), control: H(50 + sign * 10.2, 25))
                g.stroke(strand, with: .color(tones.rim.opacity(0.5)), lineWidth: len(0.8))
            }
            // A short center part / crown sheen for styled definition.
            var part = Path()
            part.move(to: H(50, 12.5))
            part.addQuadCurve(to: H(51.5, 18), control: H(50.4, 15))
            g.stroke(part, with: .color(tones.core.opacity(0.45)), lineWidth: len(0.8))
        }

        // 6) Rim-light on the major forms — the crisp holographic edge. --------------
        do {
            var g = context
            g.blendMode = .plusLighter
            let rim = StrokeStyle(lineWidth: len(1.1), lineCap: .round, lineJoin: .round)
            let rimSoft = StrokeStyle(lineWidth: len(3.2), lineCap: .round, lineJoin: .round)
            // Arms/legs get their own bright core so crossing limbs read clearly.
            let shoulderL = T(40, 33), shoulderR = T(60, 33)
            if body.seated {
                Self.strokeSeatedRim(&g, T: T, ellipseH: ellipseH, tones: tones, rim: rim)
            } else {
                let armL = limb(shoulderL, T(body.leftArm.elbow.0, body.leftArm.elbow.1), T(body.leftArm.hand.0, body.leftArm.hand.1), width: len(3.6))
                let armR = limb(shoulderR, T(body.rightArm.elbow.0, body.rightArm.elbow.1), T(body.rightArm.hand.0, body.rightArm.hand.1), width: len(3.6))
                g.stroke(armL, with: .color(tones.rim.opacity(0.42)), style: rim)
                g.stroke(armR, with: .color(tones.rim.opacity(0.42)), style: rim)
                let legL = limb(T(47, 60), T(46, 75), T(47, 88), width: len(4.4))
                let legR = limb(T(53, 60), T(54, 75), T(53, 88), width: len(4.4))
                g.stroke(legL, with: .color(tones.rim.opacity(0.20)), style: rim)
                g.stroke(legR, with: .color(tones.rim.opacity(0.20)), style: rim)
            }
            // Head + torso outline rim.
            g.stroke(ellipseH(50, 19, 6.6, 8.0), with: .color(tones.rim.opacity(0.65)), style: rim)
            g.stroke(Self.torsoOutline(T: T, seated: body.seated), with: .color(tones.rim.opacity(0.5)), style: rim)
            // A softer top-left highlight edge for the ethereal sheen.
            var sheen = Path()
            sheen.move(to: H(45, 13))
            sheen.addQuadCurve(to: H(43.5, 24), control: H(42.5, 18))
            g.stroke(sheen, with: .color(tones.core.opacity(0.5)), style: rimSoft)
        }

        // 7) Face — subtle, glowing features on the translucent skin. -----------------
        Self.drawFace(
            &context, pose: pose, frame: frame, tones: tones,
            H: H, ellipseH: ellipseH, len: len, seated: body.seated
        )

        // 8) Ambient motes + celebration sparkles (additive shimmer). -----------------
        do {
            var g = context
            g.blendMode = .plusLighter
            let motes: [(Double, Double)] = [(30, 40), (72, 34), (26, 60), (76, 58), (50, 26)]
            for (mx, my) in motes {
                let drift = (frame.sparklePhase + mx * 0.017).truncatingRemainder(dividingBy: 1)
                let y = my - drift * 16
                let tw = 0.25 + 0.75 * abs(sin((frame.sparklePhase + mx * 0.021) * .pi * 2))
                g.fill(
                    ellipseT(mx, y, 0.9 * tw, 0.9 * tw),
                    with: .color(tones.rim.opacity(0.5 * glow * tw))
                )
            }
            if pose.sparkles {
                let spots: [(Double, Double, Double)] = [
                    (17, 20, 4.0), (84, 24, 3.6), (50, 6, 3.4), (80, 48, 3.2), (18, 46, 2.9),
                ]
                for (sx, sy, sr) in spots {
                    let tw = 0.4 + 0.6 * abs(sin((frame.sparklePhase + sx * 0.013) * .pi * 2))
                    g.fill(
                        sparkle(center: T(sx, sy + dyAll * 0.2), radius: len(sr * tw)),
                        with: .color(tones.core.opacity(0.9))
                    )
                }
            }
        }

        // 9) Sleepy "z z z". ---------------------------------------------------------
        if pose.sleeping {
            let zs: [(Double, Double, Double)] = [(66, 40, 8), (74, 31, 10), (83, 21, 12)]
            for (zx, zy, fontSize) in zs {
                context.draw(
                    Text("z")
                        .font(.system(size: max(6, len(fontSize)), weight: .bold, design: .rounded))
                        .foregroundStyle(tones.rim.opacity(0.7)),
                    at: T(zx, zy)
                )
            }
        }
    }

    // MARK: Silhouette & outlines

    /// The filled union that defines the figure. Built from head, neck, torso, legs (or
    /// a seat), and both arms so a single fill keeps the translucency even.
    private static func silhouette(
        body: BodyPose,
        T: (Double, Double) -> CGPoint,
        H: (Double, Double) -> CGPoint,
        ellipseT: (Double, Double, Double, Double) -> Path,
        ellipseH: (Double, Double, Double, Double) -> Path,
        limb: (CGPoint, CGPoint, CGPoint, CGFloat) -> Path
    ) -> Path {
        var path = Path()
        // Head.
        path.addPath(ellipseH(50, 19, 6.6, 8.0))

        if body.seated {
            // Neck bridges the dropped head to the short, curled torso.
            var neck = Path()
            neck.move(to: H(47.8, 25))
            neck.addLine(to: H(52.2, 25))
            neck.addLine(to: T(53, 53))
            neck.addLine(to: T(47, 53))
            neck.closeSubpath()
            path.addPath(neck)
            // Curled torso hunching over the knees, then the hugged-knees mass.
            path.addPath(Self.torsoOutline(T: T, seated: true))
            path.addPath(ellipseT(50, 67, 15, 9))
            // Arms wrapping around the front of the knees, meeting low-center.
            let w = CGFloat(4.0) * scaleHint(T)
            path.addPath(limb(T(43, 54), T(36, 66), T(50, 74), w))
            path.addPath(limb(T(57, 54), T(64, 66), T(50, 74), w))
        } else {
            // Neck bridges the head to the standing shoulders.
            var neck = Path()
            neck.move(to: H(47.6, 25))
            neck.addLine(to: H(52.4, 25))
            neck.addLine(to: T(53, 32))
            neck.addLine(to: T(47, 32))
            neck.closeSubpath()
            path.addPath(neck)
            // Standing torso (shoulders → waist → flared hips).
            path.addPath(Self.torsoOutline(T: T, seated: false))
            // Legs.
            path.addPath(limb(T(47, 60), T(46, 75), T(47, 88), CGFloat(4.6) * scaleHint(T)))
            path.addPath(limb(T(53, 60), T(54, 75), T(53, 88), CGFloat(4.6) * scaleHint(T)))
            // Arms.
            path.addPath(limb(T(40, 33), T(body.leftArm.elbow.0, body.leftArm.elbow.1), T(body.leftArm.hand.0, body.leftArm.hand.1), CGFloat(4.0) * scaleHint(T)))
            path.addPath(limb(T(60, 33), T(body.rightArm.elbow.0, body.rightArm.elbow.1), T(body.rightArm.hand.0, body.rightArm.hand.1), CGFloat(4.0) * scaleHint(T)))
        }
        return path
    }

    /// Closed torso outline used for both the silhouette and the rim-light.
    private static func torsoOutline(
        T: (Double, Double) -> CGPoint,
        seated: Bool
    ) -> Path {
        var torso = Path()
        if seated {
            // A hunched body widening from the shoulders down to the lap.
            torso.move(to: T(44, 52))
            torso.addQuadCurve(to: T(40, 64), control: T(40, 58))
            torso.addLine(to: T(60, 64))
            torso.addQuadCurve(to: T(56, 52), control: T(60, 58))
            torso.closeSubpath()
            return torso
        }
        torso.move(to: T(39, 32))
        torso.addQuadCurve(to: T(44, 53), control: T(41, 44))    // left flank → waist
        torso.addQuadCurve(to: T(42.5, 61), control: T(43, 58))  // waist → flared hip
        torso.addLine(to: T(57.5, 61))                            // across hips
        torso.addQuadCurve(to: T(56, 53), control: T(57, 58))
        torso.addQuadCurve(to: T(61, 32), control: T(59, 44))    // waist → right shoulder
        torso.addQuadCurve(to: T(50, 30), control: T(56, 30.5))  // shoulder line → neck
        torso.addQuadCurve(to: T(39, 32), control: T(44, 30.5))
        torso.closeSubpath()
        return torso
    }

    /// Approximate device-space scale (points per design unit) from the mapper, so
    /// limb widths track the render size without threading `s` through everywhere.
    private static func scaleHint(_ T: (Double, Double) -> CGPoint) -> CGFloat {
        let a = T(0, 0), b = T(10, 0)
        return (b.x - a.x) / 10
    }

    private static func strokeSeatedRim(
        _ g: inout GraphicsContext,
        T: (Double, Double) -> CGPoint,
        ellipseH: (Double, Double, Double, Double) -> Path,
        tones: Holo,
        rim: StrokeStyle
    ) {
        // Arms wrapping around the front of the hugged knees.
        var armL = Path()
        armL.move(to: T(43, 54))
        armL.addQuadCurve(to: T(50, 74), control: T(36, 66))
        var armR = Path()
        armR.move(to: T(57, 54))
        armR.addQuadCurve(to: T(50, 74), control: T(64, 66))
        g.stroke(armL, with: .color(tones.rim.opacity(0.4)), style: rim)
        g.stroke(armR, with: .color(tones.rim.opacity(0.4)), style: rim)
        // The rounded knees the arms hug.
        g.stroke(ellipseFrom(T, 50, 67, 15, 9), with: .color(tones.rim.opacity(0.3)), style: rim)
    }

    private static func ellipseFrom(
        _ T: (Double, Double) -> CGPoint,
        _ cx: Double, _ cy: Double, _ rx: Double, _ ry: Double
    ) -> Path {
        let scale = scaleHint(T)
        let center = T(cx, cy)
        return Path(ellipseIn: CGRect(
            x: center.x - rx * scale, y: center.y - ry * scale,
            width: rx * 2 * scale, height: ry * 2 * scale
        ))
    }

    // MARK: Face

    private static func drawFace(
        _ context: inout GraphicsContext,
        pose: CompanionPose,
        frame: CompanionMotionFrame,
        tones: Holo,
        H: (Double, Double) -> CGPoint,
        ellipseH: (Double, Double, Double, Double) -> Path,
        len: (Double) -> CGFloat,
        seated: Bool
    ) {
        let eyeXs = [46.5, 53.5]
        let eyeCY = 19.5
        let lineStyle = StrokeStyle(lineWidth: len(0.9), lineCap: .round, lineJoin: .round)

        // Cheeks — a constant faint warmth plus the stronger mood blush.
        do {
            var g = context
            g.blendMode = .plusLighter
            for cheekX in [43.5, 56.5] {
                g.fill(
                    ellipseH(cheekX, 22, 2.4, 1.6),
                    with: .color(tones.rim.opacity(0.12 + 0.5 * pose.blush))
                )
            }
        }

        // Brows — worry knots the inner ends up; drawn as glowing rim lines.
        if !pose.sleeping {
            var g = context
            g.blendMode = .plusLighter
            let browY = 15.6
            let innerLift = pose.browAngle * 0.09
            for (outer, inner) in [(43.6, 48.4), (56.4, 51.6)] {
                var b = Path()
                b.move(to: H(outer, browY + 1.0))
                b.addQuadCurve(
                    to: H(inner, browY - innerLift),
                    control: H((outer + inner) / 2, browY - innerLift - 0.5)
                )
                g.stroke(b, with: .color(tones.rim.opacity(0.55)), style: lineStyle)
            }
        }

        // Eyes.
        if pose.sleeping {
            for eyeX in eyeXs { restingArc(&context, at: H(eyeX, eyeCY), tones: tones, len: len) }
        } else if pose.happyEyes {
            for eyeX in eyeXs { smilingArc(&context, at: H(eyeX, eyeCY), tones: tones, len: len) }
        } else {
            let open = max(0.06, pose.eyeOpenness * frame.blink)
            for (i, eyeX) in eyeXs.enumerated() {
                let inner = i == 0 ? 1.0 : -1.0   // toward the nose
                let ry = 1.55 * open
                // A soft almond eye: wider than tall so it reads gentle, not startled.
                context.fill(ellipseH(eyeX, eyeCY, 2.0, ry), with: .color(tones.feature.opacity(0.82)))
                if open > 0.35 {
                    // Bright iris core + a crisp catchlight.
                    var g = context
                    g.blendMode = .plusLighter
                    g.fill(ellipseH(eyeX, eyeCY + 0.1, 0.95, min(1.15, ry)), with: .color(tones.core.opacity(0.92)))
                    g.fill(ellipseH(eyeX - inner * 0.5, eyeCY - 0.55, 0.42, 0.42), with: .color(.white.opacity(0.95)))
                }
                // A soft upper lash line lifts the outer corner for a graceful eye.
                var lash = Path()
                lash.move(to: H(eyeX - inner * 2.2, eyeCY - ry * 0.5))
                lash.addQuadCurve(
                    to: H(eyeX + inner * 2.3, eyeCY - ry - 0.3),
                    control: H(eyeX, eyeCY - ry - 0.9)
                )
                context.stroke(lash, with: .color(tones.feature.opacity(0.7)), style: StrokeStyle(lineWidth: len(0.7), lineCap: .round))
            }
        }

        // Nose — the faintest tick of shadow.
        var nose = Path()
        nose.move(to: H(49.4, 21))
        nose.addQuadCurve(to: H(50.8, 22.6), control: H(49.3, 22.4))
        context.stroke(nose, with: .color(tones.feature.opacity(0.35)), style: lineStyle)

        // Mouth.
        drawMouth(&context, mouth: pose.mouth, tones: tones, H: H, len: len)
    }

    private static func restingArc(
        _ context: inout GraphicsContext, at c: CGPoint, tones: Holo, len: (Double) -> CGFloat
    ) {
        var g = context
        g.blendMode = .plusLighter
        var arc = Path()
        arc.move(to: CGPoint(x: c.x - len(2.4), y: c.y))
        arc.addQuadCurve(to: CGPoint(x: c.x + len(2.4), y: c.y), control: CGPoint(x: c.x, y: c.y + len(1.6)))
        g.stroke(arc, with: .color(tones.rim.opacity(0.75)), style: StrokeStyle(lineWidth: len(0.9), lineCap: .round))
    }

    private static func smilingArc(
        _ context: inout GraphicsContext, at c: CGPoint, tones: Holo, len: (Double) -> CGFloat
    ) {
        var g = context
        g.blendMode = .plusLighter
        var arc = Path()
        arc.move(to: CGPoint(x: c.x - len(2.4), y: c.y + len(0.5)))
        arc.addQuadCurve(to: CGPoint(x: c.x + len(2.4), y: c.y + len(0.5)), control: CGPoint(x: c.x, y: c.y - len(1.8)))
        g.stroke(arc, with: .color(tones.rim.opacity(0.85)), style: StrokeStyle(lineWidth: len(0.9), lineCap: .round))
    }

    private static func drawMouth(
        _ context: inout GraphicsContext,
        mouth: CompanionMouth,
        tones: Holo,
        H: (Double, Double) -> CGPoint,
        len: (Double) -> CGFloat
    ) {
        var g = context
        g.blendMode = .plusLighter
        let style = StrokeStyle(lineWidth: len(1.0), lineCap: .round, lineJoin: .round)
        switch mouth {
        case .smile:
            var p = Path()
            p.move(to: H(47.4, 24.4))
            p.addQuadCurve(to: H(52.6, 24.4), control: H(50, 26.4))
            g.stroke(p, with: .color(tones.rim.opacity(0.8)), style: style)
        case .flat:
            var p = Path()
            p.move(to: H(47.8, 24.8))
            p.addQuadCurve(to: H(52.2, 24.8), control: H(50, 25.1))
            g.stroke(p, with: .color(tones.rim.opacity(0.75)), style: style)
        case .frown:
            var p = Path()
            p.move(to: H(47.6, 25.4))
            p.addQuadCurve(to: H(52.4, 25.4), control: H(50, 23.6))
            g.stroke(p, with: .color(tones.rim.opacity(0.78)), style: style)
        case .grin:
            var p = Path()
            p.move(to: H(46.8, 24.0))
            p.addQuadCurve(to: H(53.2, 24.0), control: H(50, 24.8))
            p.addQuadCurve(to: H(46.8, 24.0), control: H(50, 27.4))
            p.closeSubpath()
            g.fill(p, with: .color(tones.core.opacity(0.85)))
            g.stroke(p, with: .color(tones.rim.opacity(0.7)), style: style)
        }
    }
}
