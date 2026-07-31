import AppKit
import Combine
import CoreGraphics
import Foundation
import SwiftUI

// MARK: - Element accents

extension ScreenElementKind {
    /// A stable accent per element kind, used for the overlay stroke and legend.
    var accent: Color {
        switch self {
        case .titleBar: return .gray
        case .sectionHeader: return .teal
        case .dataGrid: return .blue
        case .inputFieldStack: return .green
        case .listColumn: return .purple
        case .detailCard: return .indigo
        case .comparisonColumn: return .orange
        case .primaryButton: return .pink
        }
    }
}

// MARK: - Session (interaction state + correction persistence)

/// Drives one Screen Trainer overlay: the model's readout, the selected region,
/// and the corrections the clinician makes. Every correction is appended to the
/// PHI-free on-device store — the same signature+label memory the Python loop
/// uses. No screen capture, no network, and no PHI live here.
@MainActor
final class ScreenTrainerSession: ObservableObject {
    @Published private(set) var readout: ScreenReadout
    @Published var selectedRegionID: String?
    @Published private(set) var corrections: [ScreenTrainerCorrection]
    /// The live "what I'm learning" feed — one line per correction, any modality.
    @Published private(set) var learningEvents: [LearningEvent]
    /// The free-text feedback the clinician is typing. Submitting it records a
    /// typed correction into the same on-device store.
    @Published var typedFeedback: String = ""
    @Published var clickThrough: Bool

    private let store: ScreenTrainerCorrectionStore?
    private let clock: () -> Date
    private var eventOrdinal = 0

    init(
        readout: ScreenReadout,
        store: ScreenTrainerCorrectionStore? = nil,
        clickThrough: Bool = false,
        clock: @escaping () -> Date = Date.init
    ) {
        self.readout = readout
        self.store = store
        self.clickThrough = clickThrough
        self.clock = clock
        corrections = store?.load() ?? []
        learningEvents = []
    }

    /// The one-line current belief for the "what I'm learning" panel.
    var currentBelief: String {
        ScreenTrainerLedger.belief(for: readout, corrections: corrections)
    }

    var selectedRegion: ScreenRegion? {
        readout.regions.first { $0.id == selectedRegionID }
    }

    func select(_ id: String?) {
        selectedRegionID = id
    }

    /// Select whichever region contains a normalized point (topmost / smallest
    /// wins so an inner region stays reachable), or clear when none matches.
    func selectRegion(at point: CGPoint) {
        let hit = readout.regions
            .filter { $0.normalizedRect.contains(point) }
            .min { areaOf($0.normalizedRect) < areaOf($1.normalizedRect) }
        selectedRegionID = hit?.id
    }

    /// Cycle the selected region's element tag, mark it corrected, and narrate the
    /// change in the "what I'm learning" feed (pointer modality).
    func relabelSelectedElement() {
        guard let region = selectedRegion else { return }
        let from = region.element
        let to = from.next
        mutateSelected { $0.element = to; $0.corrected = true }
        commit(
            modality: .pointer,
            summary: "\(region.id.replacingOccurrences(of: "region-", with: "")): "
                + "\(from.displayName) → \(to.displayName)",
            note: nil,
            persist: true
        )
    }

    /// Confirm the selected region as-is (marks it corrected) and reinforce the
    /// current workflow in the on-device memory (pointer modality).
    func confirmSelected() {
        guard let region = selectedRegion else { return }
        mutateSelected { $0.corrected = true }
        commit(
            modality: .pointer,
            summary: "confirmed \(region.element.displayName) · "
                + "\(readout.workflow.displayName) reinforced",
            note: nil,
            persist: true
        )
    }

    /// Set the workflow tag the clinician believes this screen depicts, then
    /// record the correction (pointer modality).
    func setWorkflow(_ tag: WorkflowTag) {
        let from = readout.workflow
        readout.workflow = tag
        commit(
            modality: .pointer,
            summary: from == tag
                ? "\(tag.displayName) reinforced"
                : "workflow: \(from.displayName) → \(tag.displayName)",
            note: nil,
            persist: true
        )
    }

    /// Replace the selected region's rectangle (drag-resize) and mark it
    /// corrected. The rect is clamped to the window by `NormalizedRect`. Geometry
    /// nudges are not persisted to the memory (which learns the workflow, not the
    /// pixels); they surface in the feed as an adjustment.
    func resizeSelected(to rect: NormalizedRect) {
        guard let region = selectedRegion else { return }
        mutateSelected { $0.normalizedRect = rect; $0.corrected = true }
        commit(
            modality: .pointer,
            summary: "adjusted \(region.element.displayName) box",
            note: nil,
            persist: false
        )
    }

    /// Nudge one corner of the selected region to a normalized point.
    func dragCorner(_ corner: RegionCorner, to point: CGPoint) {
        guard let rect = selectedRegion?.normalizedRect else { return }
        resizeSelected(to: corner.applying(point, to: rect))
    }

    /// Submit the typed free-text feedback: capture it alongside a workflow
    /// correction in the SAME on-device store, narrate it in the feed, and clear
    /// the field. This is the typed modality of the one learning loop.
    func submitTypedFeedback() {
        let trimmed = typedFeedback.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        commit(
            modality: .typed,
            summary: "note on \(readout.workflow.displayName)",
            note: trimmed,
            persist: true
        )
        typedFeedback = ""
    }

    /// ARCHITECTED SEAM (not built in slice 1). The voice layer — mic -> local
    /// speech-to-text -> here — routes through this single method, so it teaches
    /// the exact same store and feed as pointer and typed input. Voice is added
    /// in the next slice; this keeps the plug-in point explicit and tested.
    func applyVoiceCorrection(
        workflow: WorkflowTag?,
        transcript: String
    ) {
        if let workflow { readout.workflow = workflow }
        commit(
            modality: .voice,
            summary: workflow.map { "voice: \($0.displayName)" } ?? "voice note",
            note: transcript,
            persist: true
        )
    }

    /// Replace the current readout with a fresh REAL read from the local model
    /// (produced from a just-captured, already-discarded frame). Clears the
    /// selection and narrates the read in the "what I'm learning" feed. NOTHING is
    /// persisted here: a read is the model's first guess, not a correction — the
    /// owner's confirm / relabel / drag is what teaches the on-device store. This
    /// is how the synthetic default is replaced by the model's real read.
    func applyLiveReadout(_ readout: ScreenReadout) {
        self.readout = readout
        selectedRegionID = nil
        eventOrdinal += 1
        learningEvents.append(
            LearningEvent(
                id: "learn-\(eventOrdinal)",
                modality: .pointer,
                summary: "read screen → \(readout.workflow.displayName) "
                    + "(\(readout.signature.displayName)) · \(readout.regions.count) regions",
                detail: "local model read — confirm or relabel to teach it",
                timeText: Self.timeFormatter.string(from: clock())
            )
        )
    }

    /// The single funnel every modality routes through: append a learning-feed
    /// event and, when the correction teaches the memory, persist a PHI-free
    /// exemplar to the on-device store.
    @discardableResult
    private func commit(
        modality: CorrectionModality,
        summary: String,
        note: String?,
        persist: Bool
    ) -> ScreenTrainerCorrection? {
        let now = clock()
        eventOrdinal += 1
        learningEvents.append(
            LearningEvent(
                id: "learn-\(eventOrdinal)",
                modality: modality,
                summary: summary,
                detail: note,
                timeText: Self.timeFormatter.string(from: now)
            )
        )
        guard persist else { return nil }
        let correction = ScreenTrainerCorrection(
            ts: ISO8601DateFormatter().string(from: now),
            label: readout.workflow.rawValue,
            signature: readout.signature.rawValue,
            modality: modality,
            note: note
        )
        _ = try? store?.append(correction)
        corrections.append(correction)
        return correction
    }

    private static let timeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss"
        return formatter
    }()

    /// Leave-one-out recall over the corrections taught so far, once embeddings
    /// exist. Surfaces "is it learning from me?" without any network here.
    func recallAccuracy() -> (correct: Int, scored: Int, note: String) {
        let exemplars = corrections
            .filter { !$0.embedding.isEmpty }
            .map { LabeledEmbedding(label: $0.label, embedding: $0.embedding) }
        return ScreenTrainerMemory.leaveOneOutAccuracy(exemplars)
    }

    private func mutateSelected(_ transform: (inout ScreenRegion) -> Void) {
        guard let id = selectedRegionID,
              let index = readout.regions.firstIndex(where: { $0.id == id }) else {
            return
        }
        transform(&readout.regions[index])
    }

    private func areaOf(_ rect: NormalizedRect) -> Double {
        rect.width * rect.height
    }
}

/// ARCHITECTED, not built in slice 1. The voice layer will conform to something
/// like this: capture mic audio, transcribe with an on-device recognizer (no
/// cloud), and route each recognized correction into
/// `ScreenTrainerSession.applyVoiceCorrection`. It teaches the same PHI-free store
/// and the same "what I'm learning" feed as pointer and typed input — one loop,
/// three modalities. No audio, transcript, or frame ever leaves the device, and
/// listening stays default-off and explicit, matching the app's voice posture.
@MainActor
protocol ScreenTrainerVoiceIntake {
    var isListening: Bool { get }
    func startListening()
    func stopListening()
}

// MARK: - Real capture controller (drives the "Capture / Read screen" button)

/// Orchestrates the real read: list windows → auto-suggest / pick the Citrix
/// Viewer window → capture one downscaled frame → local-model inference → hand
/// the readout to the session. The capture / read seams are injected so the
/// controller's state machine is unit-testable with a synthetic frame and never
/// touches a real screen in dev or CI. It holds no frame and no PHI: the base64
/// frame lives only inside `run(_:)` and is dropped when inference returns.
@MainActor
final class ScreenCaptureController: ObservableObject {
    enum Phase: Equatable {
        case idle
        case listing
        case choosing([CaptureCandidateWindow])
        case capturing(String)
        case reading(String)
        case done(String)
        case failed(String)
    }

    @Published private(set) var phase: Phase = .idle
    @Published private(set) var lastLatencyText: String?

    /// Hands a fresh real readout to the session (typically `applyLiveReadout`).
    private let deliver: (ScreenReadout) -> Void
    private let listWindows: () async throws -> [CaptureCandidateWindow]
    private let capture: (CGWindowID) async throws -> (base64: String, pixelWidth: Int, pixelHeight: Int)
    private let read: (String, Int, Int) async throws -> ScreenReadout
    private let now: () -> Date

    init(
        deliver: @escaping (ScreenReadout) -> Void,
        listWindows: @escaping () async throws -> [CaptureCandidateWindow] =
            { try await ScreenCaptureService.listWindows() },
        capture: @escaping (CGWindowID) async throws
            -> (base64: String, pixelWidth: Int, pixelHeight: Int) =
            { try await ScreenCaptureService.captureBase64(windowID: $0) },
        read: @escaping (String, Int, Int) async throws -> ScreenReadout =
            { try await OllamaScreenReader.read(base64Frame: $0, windowWidth: $1, windowHeight: $2) },
        now: @escaping () -> Date = Date.init
    ) {
        self.deliver = deliver
        self.listWindows = listWindows
        self.capture = capture
        self.read = read
        self.now = now
    }

    var isBusy: Bool {
        switch phase {
        case .listing, .capturing, .reading: return true
        case .idle, .choosing, .done, .failed: return false
        }
    }

    var isAuthorized: Bool { ScreenCaptureService.isAuthorized() }

    /// "Capture / Read screen": enumerate windows, then auto-capture the suggested
    /// Citrix window, or present a chooser when Citrix is not found. The UI calls
    /// this; the awaitable core is `performBeginCapture()` (used directly in tests).
    func beginCapture() {
        guard !isBusy else { return }
        Task { [weak self] in await self?.performBeginCapture() }
    }

    /// Capture and read a specific chosen window (UI entry; `run(_:)` is the core).
    func choose(_ window: CaptureCandidateWindow) {
        guard !isBusy else { return }
        Task { [weak self] in await self?.run(window) }
    }

    /// Refresh the window chooser (e.g. after opening Citrix).
    func refreshWindows() { beginCapture() }

    /// Awaitable core of `beginCapture()`: list windows and route to auto-capture
    /// or the chooser. Kept non-private so the state machine is unit-testable with
    /// injected seams and a synthetic frame — no real screen access.
    func performBeginCapture() async {
        phase = .listing
        do {
            let candidates = try await listWindows()
            if let citrix = CitrixWindowHeuristic.suggested(from: candidates) {
                await run(citrix)
            } else if candidates.isEmpty {
                phase = .failed(
                    "No capturable windows found. Grant Screen Recording and try again.")
            } else {
                phase = .choosing(candidates)
            }
        } catch {
            phase = .failed(error.localizedDescription)
        }
    }

    func run(_ window: CaptureCandidateWindow) async {
        let label = window.applicationName
        phase = .capturing(label)
        let start = now()
        do {
            let frame = try await capture(window.id)
            phase = .reading(label)
            let readout = try await read(frame.base64, frame.pixelWidth, frame.pixelHeight)
            // `frame.base64` is not retained past here — nothing is persisted.
            deliver(readout)
            let latency = now().timeIntervalSince(start)
            lastLatencyText = String(format: "read in %.1fs", latency)
            phase = .done(
                "\(readout.workflow.displayName) · \(readout.regions.count) regions")
        } catch {
            phase = .failed(error.localizedDescription)
        }
    }
}

/// Which corner of a region a drag handle adjusts.
enum RegionCorner: CaseIterable, Sendable {
    case topLeading, topTrailing, bottomLeading, bottomTrailing

    /// Return a new rect with `corner` moved to `point`, keeping the opposite
    /// corner fixed. `NormalizedRect` clamps the result into the window.
    func applying(_ point: CGPoint, to rect: NormalizedRect) -> NormalizedRect {
        let px = Double(point.x)
        let py = Double(point.y)
        let left: Double
        let top: Double
        let right: Double
        let bottom: Double
        switch self {
        case .topLeading:
            left = min(px, rect.maxX); top = min(py, rect.maxY)
            right = rect.maxX; bottom = rect.maxY
        case .topTrailing:
            left = rect.x; top = min(py, rect.maxY)
            right = max(px, rect.x); bottom = rect.maxY
        case .bottomLeading:
            left = min(px, rect.maxX); top = rect.y
            right = rect.maxX; bottom = max(py, rect.y)
        case .bottomTrailing:
            left = rect.x; top = rect.y
            right = max(px, rect.x); bottom = max(py, rect.y)
        }
        return NormalizedRect(x: left, y: top, width: right - left, height: bottom - top)
    }

    func point(in rect: NormalizedRect) -> CGPoint {
        switch self {
        case .topLeading: return CGPoint(x: rect.x, y: rect.y)
        case .topTrailing: return CGPoint(x: rect.maxX, y: rect.y)
        case .bottomLeading: return CGPoint(x: rect.x, y: rect.maxY)
        case .bottomTrailing: return CGPoint(x: rect.maxX, y: rect.maxY)
        }
    }
}

// MARK: - Regions layer (the z-index overlay)

/// Draws the model's candidate regions as labeled boxes over the target area.
/// Reused by the live overlay window and the headless demo renderer.
struct ScreenTrainerRegionsLayer: View {
    let readout: ScreenReadout
    let selectedRegionID: String?
    var showHandles: Bool = true

    var body: some View {
        GeometryReader { geometry in
            let size = geometry.size
            ZStack(alignment: .topLeading) {
                ForEach(readout.regions) { region in
                    regionBox(region, in: size)
                }
            }
            .frame(width: size.width, height: size.height)
        }
    }

    @ViewBuilder
    private func regionBox(_ region: ScreenRegion, in size: CGSize) -> some View {
        let rect = region.normalizedRect.cgRect(in: size)
        let isSelected = region.id == selectedRegionID
        let accent = region.element.accent

        ZStack(alignment: .topLeading) {
            RoundedRectangle(cornerRadius: 3)
                .strokeBorder(
                    accent,
                    style: StrokeStyle(
                        lineWidth: isSelected ? 3 : 1.6,
                        dash: region.corrected ? [] : [6, 3]
                    )
                )
                .background(
                    RoundedRectangle(cornerRadius: 3)
                        .fill(accent.opacity(isSelected ? 0.14 : 0.06))
                )
                .frame(width: rect.width, height: rect.height)

            regionTag(region, accent: accent)
                .offset(y: -1)

            if isSelected && showHandles {
                ForEach(Array(RegionCorner.allCases.enumerated()), id: \.offset) { _, corner in
                    let p = corner.point(in: region.normalizedRect)
                    Rectangle()
                        .fill(accent)
                        .frame(width: 9, height: 9)
                        .overlay(Rectangle().stroke(.white, lineWidth: 1.5))
                        .position(
                            x: (p.x - region.normalizedRect.x) * rect.width,
                            y: (p.y - region.normalizedRect.y) * rect.height
                        )
                }
            }
        }
        .frame(width: rect.width, height: rect.height, alignment: .topLeading)
        .offset(x: rect.minX, y: rect.minY)
    }

    private func regionTag(_ region: ScreenRegion, accent: Color) -> some View {
        HStack(spacing: 4) {
            Text(region.element.displayName)
                .font(.system(size: 9, weight: .bold))
            Text("\(Int(region.confidence * 100))%")
                .font(.system(size: 8, weight: .semibold).monospacedDigit())
                .opacity(0.85)
            if region.corrected {
                Image(systemName: "checkmark.seal.fill").font(.system(size: 8))
            }
        }
        .foregroundStyle(.white)
        .padding(.horizontal, 5)
        .padding(.vertical, 2)
        .background(accent, in: RoundedRectangle(cornerRadius: 3))
        .fixedSize()
    }
}

// MARK: - Live overlay view

/// The interactive overlay: a workflow banner, the regions layer, and a compact
/// correction bar. In the live window it sits transparent and always-on-top over
/// the EHR; here it is a pure SwiftUI view so it also renders headlessly.
struct ScreenTrainerOverlayView: View {
    @ObservedObject var session: ScreenTrainerSession
    @ObservedObject var captureController: ScreenCaptureController

    var body: some View {
        VStack(spacing: 0) {
            banner
            ScreenTrainerCaptureBar(controller: captureController)
            GeometryReader { geometry in
                ScreenTrainerRegionsLayer(
                    readout: session.readout,
                    selectedRegionID: session.selectedRegionID
                )
                .contentShape(Rectangle())
                .gesture(
                    DragGesture(minimumDistance: 0).onEnded { value in
                        let point = CGPoint(
                            x: value.location.x / geometry.size.width,
                            y: value.location.y / geometry.size.height
                        )
                        session.selectRegion(at: point)
                    }
                )
            }
            correctionBar
            LearningPanel(session: session)
        }
    }

    private var banner: some View {
        HStack(spacing: 8) {
            Image(systemName: "rectangle.dashed.badge.record")
            Text("Screen Trainer")
                .font(.system(size: 11, weight: .bold))
            Text("workflow: \(session.readout.workflow.displayName)")
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(.yellow)
            Text("· layout: \(session.readout.signature.displayName)")
                .font(.system(size: 10))
                .foregroundStyle(.white.opacity(0.7))
            Spacer()
            Toggle("Click-through", isOn: $session.clickThrough)
                .toggleStyle(.switch)
                .controlSize(.mini)
                .font(.system(size: 9))
        }
        .foregroundStyle(.white)
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(.black.opacity(0.72))
    }

    @ViewBuilder
    private var correctionBar: some View {
        HStack(spacing: 8) {
            if let region = session.selectedRegion {
                Text("Selected: \(region.element.displayName)")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(.white)
                Button("Relabel") { session.relabelSelectedElement() }
                    .controlSize(.mini)
                Button("Confirm") { session.confirmSelected() }
                    .controlSize(.mini)
                Text("drag a corner handle to adjust the box")
                    .font(.system(size: 9))
                    .foregroundStyle(.white.opacity(0.6))
            } else {
                Text("Click a box to confirm, relabel, or resize it.")
                    .font(.system(size: 10))
                    .foregroundStyle(.white.opacity(0.8))
            }
            Spacer()
            Text("\(session.corrections.count) corrections taught")
                .font(.system(size: 9).monospacedDigit())
                .foregroundStyle(.white.opacity(0.6))
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(.black.opacity(0.72))
    }
}

// MARK: - "What I'm learning" panel

/// The live learning feed: what it now believes, the recent corrections narrated
/// as they happen (any modality), and a typed free-text field that teaches the
/// same on-device store. Shared by the live overlay and the demo render.
struct LearningPanel: View {
    @ObservedObject var session: ScreenTrainerSession
    /// Live overlay uses the real text field; the headless demo renders a static
    /// placeholder (SwiftUI `TextField` does not rasterize cleanly offscreen).
    var interactive: Bool = true

    private static let feedbackPlaceholder =
        "Type feedback, e.g. \"the grid is the results panel\""

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Image(systemName: "brain.head.profile").font(.system(size: 10))
                Text("WHAT I'M LEARNING")
                    .font(.system(size: 9, weight: .bold))
                Spacer()
                Text("\(session.corrections.count) taught")
                    .font(.system(size: 9).monospacedDigit())
                    .foregroundStyle(.white.opacity(0.6))
            }
            .foregroundStyle(.white)

            Text(session.currentBelief)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(.yellow)
                .fixedSize(horizontal: false, vertical: true)

            VStack(alignment: .leading, spacing: 3) {
                if session.learningEvents.isEmpty {
                    Text("Correct a box, pick a workflow, or type a note — I'll show what changed here.")
                        .font(.system(size: 10))
                        .foregroundStyle(.white.opacity(0.55))
                } else {
                    ForEach(session.learningEvents.suffix(4).reversed()) { event in
                        eventRow(event)
                    }
                }
            }

            HStack(spacing: 6) {
                Image(systemName: "keyboard").font(.system(size: 10))
                if interactive {
                    TextField(Self.feedbackPlaceholder, text: $session.typedFeedback)
                        .textFieldStyle(.roundedBorder)
                        .font(.system(size: 10))
                        .onSubmit { session.submitTypedFeedback() }
                    Button("Teach") { session.submitTypedFeedback() }
                        .controlSize(.mini)
                        .disabled(session.typedFeedback.trimmingCharacters(in: .whitespaces).isEmpty)
                } else {
                    Text(Self.feedbackPlaceholder)
                        .font(.system(size: 10))
                        .foregroundStyle(.white.opacity(0.4))
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 7)
                        .padding(.vertical, 4)
                        .background(
                            RoundedRectangle(cornerRadius: 5)
                                .fill(.white.opacity(0.08))
                                .overlay(
                                    RoundedRectangle(cornerRadius: 5)
                                        .stroke(.white.opacity(0.25), lineWidth: 1)
                                )
                        )
                    Text("Teach")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(.white.opacity(0.5))
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(.white.opacity(0.12), in: RoundedRectangle(cornerRadius: 5))
                }
            }

            HStack(spacing: 5) {
                Image(systemName: "mic.slash").font(.system(size: 9))
                Text("Voice teaching arrives next — mic → on-device speech → this same feed.")
                    .font(.system(size: 9))
            }
            .foregroundStyle(.white.opacity(0.45))
        }
        .foregroundStyle(.white)
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(.black.opacity(0.78))
    }

    private func eventRow(_ event: LearningEvent) -> some View {
        HStack(alignment: .top, spacing: 6) {
            Image(systemName: event.modality.symbolName)
                .font(.system(size: 9))
                .foregroundStyle(.cyan)
                .frame(width: 14)
            VStack(alignment: .leading, spacing: 1) {
                Text(event.summary)
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(.white)
                if let detail = event.detail {
                    Text("“\(detail)”")
                        .font(.system(size: 9))
                        .foregroundStyle(.white.opacity(0.7))
                        .lineLimit(2)
                }
            }
            Spacer(minLength: 4)
            Text(event.timeText)
                .font(.system(size: 8).monospacedDigit())
                .foregroundStyle(.white.opacity(0.45))
        }
    }
}

// MARK: - Capture bar (the real "read my screen" control)

/// The overlay's real-capture control: a "Capture / Read screen" button, a live
/// status line, and — when the Citrix window is not auto-found — a window
/// chooser. Every path drives `ScreenCaptureController`; nothing here holds a
/// frame or any PHI.
struct ScreenTrainerCaptureBar: View {
    @ObservedObject var controller: ScreenCaptureController

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 8) {
                Button {
                    controller.beginCapture()
                } label: {
                    Label("Capture / Read screen", systemImage: "camera.viewfinder")
                        .font(.system(size: 10, weight: .semibold))
                }
                .controlSize(.small)
                .disabled(controller.isBusy)

                statusView

                Spacer()

                if !controller.isAuthorized {
                    Label("Screen Recording off", systemImage: "exclamationmark.triangle.fill")
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundStyle(.orange)
                }
                if let latency = controller.lastLatencyText {
                    Text(latency)
                        .font(.system(size: 9).monospacedDigit())
                        .foregroundStyle(.white.opacity(0.6))
                }
            }

            if case .choosing(let windows) = controller.phase {
                chooser(windows)
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(.black.opacity(0.72))
    }

    @ViewBuilder
    private var statusView: some View {
        switch controller.phase {
        case .idle:
            Text("Reads the picked window with the local model — nothing leaves this Mac.")
                .font(.system(size: 9))
                .foregroundStyle(.white.opacity(0.6))
        case .listing:
            busy("Finding windows…")
        case .choosing:
            Text("Pick the window to read:")
                .font(.system(size: 9, weight: .semibold))
                .foregroundStyle(.white.opacity(0.8))
        case .capturing(let label):
            busy("Capturing \(label)…")
        case .reading(let label):
            busy("Local model reading \(label)…")
        case .done(let summary):
            Label("Read: \(summary)", systemImage: "checkmark.seal.fill")
                .font(.system(size: 9, weight: .semibold))
                .foregroundStyle(.green)
        case .failed(let message):
            Label(message, systemImage: "xmark.octagon.fill")
                .font(.system(size: 9))
                .foregroundStyle(.orange)
                .lineLimit(2)
        }
    }

    private func busy(_ text: String) -> some View {
        HStack(spacing: 5) {
            ProgressView().controlSize(.mini)
            Text(text).font(.system(size: 9)).foregroundStyle(.white.opacity(0.8))
        }
    }

    private func chooser(_ windows: [CaptureCandidateWindow]) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                ForEach(windows.prefix(12)) { window in
                    Button {
                        controller.choose(window)
                    } label: {
                        HStack(spacing: 4) {
                            if window.isCitrixViewer {
                                Image(systemName: "star.fill").font(.system(size: 8))
                            }
                            Text(window.pickerLabel)
                                .font(.system(size: 9))
                                .lineLimit(1)
                        }
                    }
                    .controlSize(.mini)
                    .tint(window.isCitrixViewer ? .yellow : nil)
                }
            }
            .padding(.vertical, 1)
        }
        .frame(maxHeight: 26)
    }
}

// MARK: - Overlay window (transparent, always-on-top, click-through toggle)

/// Hosts the overlay in a borderless, transparent, floating window that can join
/// all Spaces and be made click-through so the clinician keeps working in the EHR
/// beneath it. It never captures pixels; it only *draws over* the screen. Real
/// capture, when wired, happens out-of-band and feeds only the local model.
@MainActor
final class ScreenTrainerOverlayWindowController {
    private var window: NSWindow?
    private let session: ScreenTrainerSession
    private let captureController: ScreenCaptureController

    init(session: ScreenTrainerSession) {
        self.session = session
        // Wire the real-capture controller to feed the model's read into the
        // session, replacing the synthetic default. Deliver hops to the main
        // actor because `ScreenCaptureController` is @MainActor.
        self.captureController = ScreenCaptureController(
            deliver: { [weak session] readout in
                session?.applyLiveReadout(readout)
            }
        )
    }

    @discardableResult
    func show() -> NSWindow {
        let window = self.window ?? makeWindow()
        window.orderFrontRegardless()
        applyClickThrough(session.clickThrough)
        return window
    }

    func close() {
        window?.orderOut(nil)
    }

    func setClickThrough(_ enabled: Bool) {
        session.clickThrough = enabled
        applyClickThrough(enabled)
    }

    private func applyClickThrough(_ enabled: Bool) {
        window?.ignoresMouseEvents = enabled
    }

    private func makeWindow() -> NSWindow {
        let size = NSSize(width: 720, height: 664)
        let window = NSWindow(
            contentRect: NSRect(origin: .zero, size: size),
            styleMask: [.borderless],
            backing: .buffered,
            defer: false
        )
        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = false
        window.level = .floating
        window.isMovableByWindowBackground = true
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        window.isReleasedWhenClosed = false
        window.contentView = NSHostingView(
            rootView: ScreenTrainerOverlayView(
                session: session,
                captureController: captureController
            )
        )
        window.center()
        self.window = window
        return window
    }
}

// MARK: - Headless demo renderer

/// Renders a still demo of the Screen Trainer over a synthetic EHR frame to a
/// PNG, without opening or foregrounding any window — so the concept can be
/// reviewed as an image. Mirrors `CompanionPreviewRenderer`. Only synthetic
/// frames are ever used; no real capture and no PHI are involved.
enum ScreenTrainerDemoRenderer {
    static let argument = "--render-trainer-demo"
    static let frameArgument = "--trainer-demo-frame"
    static let labelArgument = "--trainer-demo-label"

    static func requestedOutputPath(
        arguments: [String] = ProcessInfo.processInfo.arguments
    ) -> String? {
        value(for: argument, in: arguments)
    }

    static func requestedFramePath(
        arguments: [String] = ProcessInfo.processInfo.arguments
    ) -> String? {
        value(for: frameArgument, in: arguments)
    }

    static func requestedLabel(
        arguments: [String] = ProcessInfo.processInfo.arguments
    ) -> WorkflowTag {
        value(for: labelArgument, in: arguments)
            .flatMap(WorkflowTag.init(rawValue:)) ?? .resultsReview
    }

    private static func value(for flag: String, in arguments: [String]) -> String? {
        guard let index = arguments.firstIndex(of: flag), index + 1 < arguments.count else {
            return nil
        }
        return arguments[index + 1]
    }

    @MainActor
    static func render(
        to path: String,
        framePath: String?,
        label: WorkflowTag,
        scale: CGFloat = 2
    ) -> Bool {
        let session = ScreenTrainerSession(
            readout: SyntheticScreenTrainerModel.readout(for: label),
            clock: { Date(timeIntervalSince1970: 1_753_900_000) }
        )
        // Simulate a short teaching burst so the demo shows real corrections and
        // a populated "what I'm learning" feed, not just first-pass detection.
        if let primary = session.readout.regions.first(where: {
            $0.element == .dataGrid || $0.element == .inputFieldStack
                || $0.element == .listColumn || $0.element == .comparisonColumn
        }) {
            session.select(primary.id)
            session.confirmSelected()  // pointer: reinforce this workflow
        }
        session.typedFeedback = "the big grid is the results panel"
        session.submitTypedFeedback()  // typed: same store, with a note
        // Re-select the primary region so the demo shows the selected box with
        // its drag handles and correction chip.
        if let primary = session.readout.regions.first(where: {
            $0.element == .dataGrid || $0.element == .inputFieldStack
                || $0.element == .listColumn || $0.element == .comparisonColumn
        }) {
            session.select(primary.id)
        }
        let content = ScreenTrainerDemoView(session: session, framePath: framePath)
            .frame(width: 1_180, height: 760)
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

/// The composited demo: caption, the synthetic EHR frame with the overlay drawn
/// on top beside the live "what I'm learning" panel, and a legend explaining the
/// correction loop and PHI boundary.
struct ScreenTrainerDemoView: View {
    @ObservedObject var session: ScreenTrainerSession
    let framePath: String?

    private static let frameSize = CGSize(width: 760, height: 520)

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            caption
            HStack(alignment: .top, spacing: 12) {
                frameWithOverlay
                LearningPanel(session: session, interactive: false)
                    .frame(width: 360)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
            }
            .padding(.horizontal, 14)
            legend
        }
        .background(Color(red: 0.09, green: 0.10, blue: 0.12))
    }

    private var caption: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text("Screen Trainer — the local model's read, drawn on your screen")
                .font(.system(size: 16, weight: .bold))
                .foregroundStyle(.white)
            Text(
                "The local vision model marks where it thinks the EHR elements sit. "
                    + "You confirm, relabel, or drag a box — or type a note — and the "
                    + "\"what I'm learning\" panel narrates what changed and what it now "
                    + "believes. Every modality teaches one on-device memory. No frame or "
                    + "text ever leaves the machine."
            )
            .font(.system(size: 11))
            .foregroundStyle(.white.opacity(0.75))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
    }

    private var frameWithOverlay: some View {
        ZStack(alignment: .topLeading) {
            frameBackground
            ScreenTrainerRegionsLayer(
                readout: session.readout,
                selectedRegionID: session.selectedRegionID
            )
            relabelChip
        }
        .frame(width: Self.frameSize.width, height: Self.frameSize.height)
        .clipped()
        .overlay(
            RoundedRectangle(cornerRadius: 4)
                .stroke(.white.opacity(0.15), lineWidth: 1)
        )
    }

    @ViewBuilder
    private var frameBackground: some View {
        if let framePath, let image = NSImage(contentsOfFile: framePath) {
            Image(nsImage: image)
                .resizable()
                .aspectRatio(contentMode: .fill)
                .frame(width: Self.frameSize.width, height: Self.frameSize.height)
        } else {
            // Self-contained fallback so the render never fails when a synthetic
            // frame file is absent. Still content-free — plain panels only.
            Rectangle()
                .fill(Color(red: 0.96, green: 0.96, blue: 0.97))
                .frame(width: Self.frameSize.width, height: Self.frameSize.height)
                .overlay(alignment: .top) {
                    Rectangle().fill(Color(red: 0.11, green: 0.2, blue: 0.37))
                        .frame(height: 28)
                }
        }
    }

    /// A floating chip that shows the correction affordance on the selected box.
    @ViewBuilder
    private var relabelChip: some View {
        if let region = session.selectedRegion {
            let rect = region.normalizedRect.cgRect(in: Self.frameSize)
            HStack(spacing: 6) {
                Image(systemName: "hand.tap.fill").font(.system(size: 9))
                Text("Confirm").font(.system(size: 10, weight: .bold))
                Text("· Relabel").font(.system(size: 10))
                Text("· Drag corners").font(.system(size: 10))
            }
            .foregroundStyle(.white)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(.black.opacity(0.82), in: Capsule())
            .offset(
                x: min(rect.midX - 60, Self.frameSize.width - 190),
                y: max(6, rect.minY + 18)
            )
        }
    }

    private var legend: some View {
        HStack(alignment: .top, spacing: 16) {
            VStack(alignment: .leading, spacing: 4) {
                Text("ELEMENT TAGS DETECTED")
                    .font(.system(size: 9, weight: .bold))
                    .foregroundStyle(.white.opacity(0.6))
                ForEach(distinctElements, id: \.self) { element in
                    HStack(spacing: 6) {
                        Rectangle().fill(element.accent).frame(width: 11, height: 11)
                        Text(element.displayName)
                            .font(.system(size: 10))
                            .foregroundStyle(.white.opacity(0.85))
                    }
                }
            }
            Spacer()
            VStack(alignment: .leading, spacing: 4) {
                Text("PHI BOUNDARY")
                    .font(.system(size: 9, weight: .bold))
                    .foregroundStyle(.white.opacity(0.6))
                Label("Synthetic frame — no real EHR", systemImage: "checkmark.shield.fill")
                Label("Boxes are normalized geometry, not pixels", systemImage: "square.dashed")
                Label("Corrections store a tag only, on-device", systemImage: "internaldrive.fill")
            }
            .font(.system(size: 10))
            .foregroundStyle(.green.opacity(0.85))
        }
        .padding(14)
    }

    private var distinctElements: [ScreenElementKind] {
        var seen: [ScreenElementKind] = []
        for region in session.readout.regions where !seen.contains(region.element) {
            seen.append(region.element)
        }
        return seen
    }
}
