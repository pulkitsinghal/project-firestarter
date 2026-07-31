import CoreGraphics
import Foundation

// MARK: - Screen Trainer model (content-free by construction)
//
// The Screen Trainer is the visual face of the local "watch me work" learning
// loop. A local vision model (qwen2.5vl over localhost Ollama) reads a screen's
// GEOMETRY and returns candidate regions marking where it thinks the EHR
// elements / workflow areas sit. The overlay draws those boxes; the clinician
// corrects them (confirm / relabel / drag); each correction is appended to the
// same PHI-free signature+label memory the Python `watchful_memory.py` loop uses.
//
// PHI BOUNDARY (absolute): nothing in this file is or can become PHI. Regions
// are normalized rectangles (0...1) plus a structure-only element tag and a
// workflow tag — never pixels, never screen text, never a patient value, never
// an absolute screen position. Real frames are seen only by the local model at
// runtime on the clinician's machine and deleted after inference; they never
// enter this process's model or persistence. The synthetic model below drives
// every demo and test so no real capture is ever required to exercise the loop.

/// The macro-layout signature the local vision model assigns to a screen. This
/// one clean, content-free token — never the verbose read — is the learning
/// substrate the memory embeds. Mirrors `watchful_train.py` `LAYOUT_TAGS`.
enum ScreenLayoutSignature: String, Codable, CaseIterable, Sendable {
    case stackedForm = "stacked-form"
    case fullWidthGrid = "full-width-grid"
    case leftListRightDetail = "left-list-right-detail"
    case twoParallelColumns = "two-parallel-columns"

    var displayName: String {
        rawValue.replacingOccurrences(of: "-", with: " ")
    }
}

/// The clinical workflow step a screen depicts — the closed vocabulary the
/// clinician confirms or relabels. Mirrors `synthetic_ehr.py` `LABELS`. A tag is
/// a workflow name, never patient content, so it is never PHI.
enum WorkflowTag: String, Codable, CaseIterable, Sendable {
    case orderEntry = "order-entry"
    case resultsReview = "results-review"
    case problemList = "problem-list"
    case medReconciliation = "med-reconciliation"

    var displayName: String {
        rawValue.replacingOccurrences(of: "-", with: " ")
    }

    /// The macro layout each synthetic workflow presents. This is the same
    /// mapping `synthetic_ehr.py` renders and `watchful_train.py` tags.
    var defaultSignature: ScreenLayoutSignature {
        switch self {
        case .orderEntry: return .stackedForm
        case .resultsReview: return .fullWidthGrid
        case .problemList: return .leftListRightDetail
        case .medReconciliation: return .twoParallelColumns
        }
    }
}

/// The kind of UI element a detected region marks. Structure only — the label
/// describes what a region *is* (a grid, a button), never what it *contains*.
enum ScreenElementKind: String, Codable, CaseIterable, Sendable {
    case titleBar = "title-bar"
    case sectionHeader = "section-header"
    case dataGrid = "data-grid"
    case inputFieldStack = "input-field-stack"
    case listColumn = "list-column"
    case detailCard = "detail-card"
    case comparisonColumn = "comparison-column"
    case primaryButton = "primary-button"

    var displayName: String {
        rawValue.replacingOccurrences(of: "-", with: " ")
    }

    /// A stable ordering used to cycle the element tag during a relabel.
    static var cycle: [ScreenElementKind] { allCases }

    /// The next tag when the clinician relabels an element region.
    var next: ScreenElementKind {
        let all = Self.cycle
        let index = all.firstIndex(of: self) ?? 0
        return all[(index + 1) % all.count]
    }
}

/// A rectangle normalized to the captured window: origin at the top-left,
/// each axis in `0...1`. Carries no pixels and no absolute screen coordinate, so
/// it cannot localize a real screen or leak PHI. Values are always clamped.
struct NormalizedRect: Equatable, Codable, Sendable {
    var x: Double
    var y: Double
    var width: Double
    var height: Double

    init(x: Double, y: Double, width: Double, height: Double) {
        self.x = NormalizedRect.clampOrigin(x)
        self.y = NormalizedRect.clampOrigin(y)
        self.width = NormalizedRect.clampExtent(width, origin: self.x)
        self.height = NormalizedRect.clampExtent(height, origin: self.y)
    }

    private static func clampOrigin(_ value: Double) -> Double {
        guard value.isFinite else { return 0 }
        return min(1, max(0, value))
    }

    private static func clampExtent(_ value: Double, origin: Double) -> Double {
        guard value.isFinite, value > 0 else { return 0 }
        return min(1 - origin, value)
    }

    var maxX: Double { x + width }
    var maxY: Double { y + height }

    func contains(_ point: CGPoint) -> Bool {
        Double(point.x) >= x && Double(point.x) <= maxX
            && Double(point.y) >= y && Double(point.y) <= maxY
    }

    /// The pixel rectangle this normalized rect maps to inside a view of `size`.
    func cgRect(in size: CGSize) -> CGRect {
        CGRect(
            x: x * Double(size.width),
            y: y * Double(size.height),
            width: width * Double(size.width),
            height: height * Double(size.height)
        )
    }
}

/// One candidate region the model believes marks an EHR element / workflow area.
struct ScreenRegion: Identifiable, Equatable, Codable, Sendable {
    let id: String
    var element: ScreenElementKind
    var normalizedRect: NormalizedRect
    /// The model's confidence in this region, `0...1`.
    var confidence: Double
    /// True once the clinician has confirmed or relabeled this region.
    var corrected: Bool

    init(
        id: String,
        element: ScreenElementKind,
        normalizedRect: NormalizedRect,
        confidence: Double,
        corrected: Bool = false
    ) {
        self.id = id
        self.element = element
        self.normalizedRect = normalizedRect
        self.confidence = min(1, max(0, confidence))
        self.corrected = corrected
    }
}

/// The local vision model's full read of one frame: window dimensions, the macro
/// layout signature, a best-guess workflow, and the element regions. Everything
/// is content-free structure — the payload the overlay draws and the clinician
/// corrects.
struct ScreenReadout: Equatable, Codable, Sendable {
    var windowWidth: Int
    var windowHeight: Int
    var signature: ScreenLayoutSignature
    var workflow: WorkflowTag
    var regions: [ScreenRegion]

    /// The aspect ratio of the captured window, used to size the overlay canvas.
    var aspectRatio: CGFloat {
        guard windowHeight > 0 else { return 16.0 / 10.0 }
        return CGFloat(windowWidth) / CGFloat(windowHeight)
    }
}

// MARK: - Synthetic vision model (offline demo + tests)

/// Produces a deterministic, content-free readout for a synthetic EHR frame with
/// a KNOWN layout. This stands in for the local vision model so the whole loop —
/// overlay draw, correct, persist — can be exercised in the demo and unit tests
/// without any screen capture, any network, and any risk of PHI. The live model
/// is `OllamaScreenReader`; this returns the same `ScreenReadout` shape it will.
///
/// The region rectangles mirror the geometry `synthetic_ehr.py` draws, so the
/// boxes land on the fake panels in the demo frame.
enum SyntheticScreenTrainerModel {
    static func readout(
        for label: WorkflowTag,
        windowWidth: Int = 1_100,
        windowHeight: Int = 760
    ) -> ScreenReadout {
        ScreenReadout(
            windowWidth: windowWidth,
            windowHeight: windowHeight,
            signature: label.defaultSignature,
            workflow: label,
            regions: regions(for: label)
        )
    }

    private static func region(
        _ suffix: String,
        _ element: ScreenElementKind,
        _ x: Double,
        _ y: Double,
        _ width: Double,
        _ height: Double,
        _ confidence: Double
    ) -> ScreenRegion {
        ScreenRegion(
            id: "region-\(suffix)",
            element: element,
            normalizedRect: NormalizedRect(x: x, y: y, width: width, height: height),
            confidence: confidence
        )
    }

    private static func titleBar(_ confidence: Double = 0.88) -> ScreenRegion {
        region("title-bar", .titleBar, 0.0, 0.0, 1.0, 0.053, confidence)
    }

    private static func regions(for label: WorkflowTag) -> [ScreenRegion] {
        switch label {
        case .resultsReview:
            return [
                titleBar(),
                region("grid-header", .sectionHeader, 0.022, 0.068, 0.956, 0.047, 0.83),
                region("grid-body", .dataGrid, 0.022, 0.115, 0.956, 0.86, 0.94),
            ]
        case .orderEntry:
            return [
                titleBar(),
                region("form-header", .sectionHeader, 0.022, 0.068, 0.956, 0.045, 0.8),
                region("field-stack", .inputFieldStack, 0.022, 0.15, 0.956, 0.7, 0.9),
                region("submit", .primaryButton, 0.778, 0.905, 0.2, 0.06, 0.86),
            ]
        case .problemList:
            return [
                titleBar(),
                region("list", .listColumn, 0.022, 0.068, 0.247, 0.906, 0.9),
                region("detail", .detailCard, 0.29, 0.068, 0.688, 0.906, 0.88),
                region("detail-title", .sectionHeader, 0.31, 0.095, 0.62, 0.052, 0.72),
            ]
        case .medReconciliation:
            return [
                titleBar(),
                region("home-meds", .comparisonColumn, 0.022, 0.068, 0.458, 0.906, 0.9),
                region("hospital-meds", .comparisonColumn, 0.52, 0.068, 0.458, 0.906, 0.9),
            ]
        }
    }
}

// MARK: - On-device learning loop (ported from watchful_memory.py)

/// One PHI-free exemplar: a workflow label and its embedding. Mirrors the record
/// `watchful_memory.py` embeds and classifies. The embedding is produced locally
/// (nomic-embed-text over localhost) from the content-free layout signature.
struct LabeledEmbedding: Equatable, Sendable {
    let label: String
    let embedding: [Double]
}

/// Nearest-class-centroid classification over the clinician's accumulated
/// corrections — a genuine, incremental, on-device few-shot memory that starts
/// empty and improves as corrections accrue. This is a faithful Swift port of the
/// same algorithm in `watchful_memory.py`, so the native overlay and the Python
/// readout share one learning loop.
enum ScreenTrainerMemory {
    static func cosine(_ a: [Double], _ b: [Double]) -> Double {
        guard a.count == b.count else { return 0 }
        return zip(a, b).reduce(0) { $0 + $1.0 * $1.1 }
    }

    /// L2-normalize a vector; a zero vector is returned unchanged.
    static func normalize(_ v: [Double]) -> [Double] {
        let norm = (v.reduce(0) { $0 + $1 * $1 }).squareRoot()
        guard norm > 0 else { return v }
        return v.map { $0 / norm }
    }

    /// Mean (L2-normalized) embedding per label.
    static func centroids(_ exemplars: [LabeledEmbedding]) -> [String: [Double]] {
        var buckets: [String: [[Double]]] = [:]
        for exemplar in exemplars {
            buckets[exemplar.label, default: []].append(exemplar.embedding)
        }
        var result: [String: [Double]] = [:]
        for (label, vectors) in buckets {
            guard let width = vectors.first?.count, width > 0 else { continue }
            var mean = [Double](repeating: 0, count: width)
            for vector in vectors where vector.count == width {
                for index in 0..<width { mean[index] += vector[index] }
            }
            let count = Double(vectors.count)
            mean = mean.map { $0 / count }
            result[label] = normalize(mean)
        }
        return result
    }

    /// Nearest centroid for `vec`, with confidence mapped from cosine `[-1,1]`
    /// into `[0,1]`. Returns `(nil, 0)` when the memory is empty.
    static func classify(
        _ centroids: [String: [Double]],
        _ vec: [Double]
    ) -> (label: String?, confidence: Double) {
        guard !centroids.isEmpty else { return (nil, 0) }
        var best: (label: String, score: Double)?
        for (label, centroid) in centroids {
            let score = cosine(vec, centroid)
            if best == nil || score > best!.score {
                best = (label, score)
            }
        }
        guard let best else { return (nil, 0) }
        return (best.label, (best.score + 1.0) / 2.0)
    }

    /// Leave-one-out nearest-centroid accuracy over the clinician's OWN
    /// corrections — "does my teaching predict my next correction?". Only items
    /// whose class has at least two examples are scored.
    static func leaveOneOutAccuracy(
        _ exemplars: [LabeledEmbedding]
    ) -> (correct: Int, scored: Int, note: String) {
        var counts: [String: Int] = [:]
        for exemplar in exemplars { counts[exemplar.label, default: 0] += 1 }
        let scorable = exemplars.indices.filter { counts[exemplars[$0].label, default: 0] >= 2 }
        guard scorable.count >= 2 else {
            return (0, 0, "need >=2 corrections in >=2 workflow tags to score")
        }
        var correct = 0
        for index in scorable {
            let rest = exemplars.enumerated()
                .filter { $0.offset != index }
                .map { $0.element }
            let (predicted, _) = classify(centroids(rest), exemplars[index].embedding)
            if predicted == exemplars[index].label { correct += 1 }
        }
        return (correct, scorable.count, "scored \(scorable.count)/\(exemplars.count) corrections")
    }
}

// MARK: - Correction modality (one loop, many inputs)

/// How a correction reached the loop. Pointer (click/drag) and typed free-text
/// feedback are built in slice 1; `voice` is ARCHITECTED here so the next layer
/// (mic -> local speech-to-text -> the same funnel) plugs in without touching the
/// store, the memory, or the overlay. Every modality feeds the ONE PHI-free
/// on-device store below.
enum CorrectionModality: String, Codable, CaseIterable, Sendable {
    case pointer
    case typed
    case voice

    var displayName: String {
        switch self {
        case .pointer: return "pointer"
        case .typed: return "typed"
        case .voice: return "voice"
        }
    }

    var symbolName: String {
        switch self {
        case .pointer: return "hand.point.up.left.fill"
        case .typed: return "keyboard.fill"
        case .voice: return "mic.fill"
        }
    }
}

// MARK: - Learning ledger ("what I'm learning")

/// One human-readable line for the live "what I'm learning" panel. Produced when
/// the clinician corrects something, regardless of modality, so pointer, typed,
/// and (later) voice all narrate through the same feed.
struct LearningEvent: Identifiable, Equatable, Sendable {
    let id: String
    let modality: CorrectionModality
    /// The short headline, e.g. "grid-body: data-grid → list-column".
    let summary: String
    /// Optional extra context, e.g. the clinician's typed note.
    let detail: String?
    /// A short, preformatted timestamp for display.
    let timeText: String
}

/// Derives the "what it now believes" summary from accumulated corrections. Pure
/// so the panel text is testable without any UI or network.
enum ScreenTrainerLedger {
    /// How many times the clinician has reinforced a given workflow label.
    static func reinforcementCount(
        _ corrections: [ScreenTrainerCorrection],
        label: String
    ) -> Int {
        corrections.lazy.filter { $0.label == label }.count
    }

    /// A one-line current belief for a readout given corrections so far.
    static func belief(
        for readout: ScreenReadout,
        corrections: [ScreenTrainerCorrection]
    ) -> String {
        let count = reinforcementCount(corrections, label: readout.workflow.rawValue)
        let base = "This screen → \(readout.workflow.displayName) "
            + "(\(readout.signature.displayName))"
        switch count {
        case 0: return base + " · not yet reinforced"
        case 1: return base + " · reinforced 1×"
        default: return base + " · reinforced \(count)×"
        }
    }
}

// MARK: - Correction store (PHI-free, JSONL — shared with watchful_memory.py)

/// One persisted correction. This is a superset of the
/// `{ts,label,signature,embedding}` shape `watchful_memory.py` writes, one JSON
/// object per line, so the native overlay and the Python loop append to the same
/// on-device store (the Python reader ignores the extra keys). It records only a
/// layout signature token, a workflow tag, an optional local embedding, the input
/// modality, and — only when the clinician types one — his own free-text teaching
/// note.
///
/// PHI boundary: nothing here is extracted from the EHR screen. The signature and
/// tags are content-free geometry; the `note` is the clinician's OWN annotation,
/// authored by him, kept on-device only, and never embedded or transmitted. No
/// frame, no pixels, no screen text. Never PHI.
struct ScreenTrainerCorrection: Equatable, Codable, Sendable {
    let ts: String
    /// The workflow tag the clinician confirmed or corrected to.
    let label: String
    /// The content-free macro-layout signature token.
    let signature: String
    /// Local embedding of the signature. Empty until the local embed model
    /// (nomic-embed-text over localhost) backfills it; the geometry loop attaches
    /// it exactly as `watchful_memory.add_exemplar` does.
    let embedding: [Double]
    /// Which input produced this correction (pointer / typed / voice).
    let modality: String?
    /// The clinician's own free-text teaching note, when he typed one. On-device
    /// only; never embedded, never sent.
    let note: String?

    init(
        ts: String,
        label: String,
        signature: String,
        embedding: [Double] = [],
        modality: CorrectionModality? = nil,
        note: String? = nil
    ) {
        self.ts = ts
        self.label = label
        self.signature = signature
        self.embedding = embedding
        self.modality = modality?.rawValue
        let trimmed = note?.trimmingCharacters(in: .whitespacesAndNewlines)
        self.note = (trimmed?.isEmpty ?? true) ? nil : trimmed
    }
}

/// Append-only JSONL persistence for corrections. Load tolerates blank and
/// corrupt lines exactly like `watchful_memory.load_memory`.
final class ScreenTrainerCorrectionStore {
    private let fileURL: URL

    init(fileURL: URL) {
        self.fileURL = fileURL
    }

    /// The default on-device store path, git-ignored and never transmitted.
    static func defaultStore(source: String = "citrix-ehr") -> ScreenTrainerCorrectionStore {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        let safe = source.map { $0.isLetter || $0.isNumber || $0 == "-" || $0 == "_" ? $0 : "-" }
        let dir = base
            .appendingPathComponent("OperationsFloater", isDirectory: true)
            .appendingPathComponent("screen-trainer-memory", isDirectory: true)
        return ScreenTrainerCorrectionStore(
            fileURL: dir.appendingPathComponent("\(String(safe)).jsonl")
        )
    }

    @discardableResult
    func append(_ correction: ScreenTrainerCorrection) throws -> ScreenTrainerCorrection {
        try FileManager.default.createDirectory(
            at: fileURL.deletingLastPathComponent(),
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        var line = try encoder.encode(correction)
        line.append(0x0A)  // newline

        if FileManager.default.fileExists(atPath: fileURL.path) {
            let handle = try FileHandle(forWritingTo: fileURL)
            defer { try? handle.close() }
            try handle.seekToEnd()
            try handle.write(contentsOf: line)
        } else {
            try line.write(to: fileURL, options: [.atomic])
        }
        return correction
    }

    func load() -> [ScreenTrainerCorrection] {
        guard let text = try? String(contentsOf: fileURL, encoding: .utf8) else { return [] }
        let decoder = JSONDecoder()
        return text.split(separator: "\n").compactMap { rawLine in
            let trimmed = rawLine.trimmingCharacters(in: .whitespaces)
            guard !trimmed.isEmpty, let data = trimmed.data(using: .utf8) else { return nil }
            return try? decoder.decode(ScreenTrainerCorrection.self, from: data)
        }
    }
}

// MARK: - Live vision path (wired, not productionized)

/// The seams the live path uses to turn a frame into a `ScreenReadout` from the
/// local qwen2.5vl model. The actual capture + network call runs ONLY on the
/// clinician's machine at runtime (frame -> `http://localhost:11434` only, then
/// deleted); these pure request/parse functions make the wiring reviewable and
/// testable without ever capturing or loading a real frame. No frame ever
/// reaches this process here — the synthetic model drives demo and tests.
enum OllamaScreenReader {
    static let endpoint = URL(string: "http://localhost:11434/api/generate")!
    static let visionModel = "qwen2.5vl:7b"

    /// A structure-only region prompt in the same spirit as the geometry prompt
    /// in `watchful_train.py`: describe WHERE elements sit, never WHAT they say.
    static let regionPrompt = """
        You are a screen-LAYOUT analyst calibrating a clinical workflow assistant.
        Return ONLY compact JSON describing the geometry of this EHR screen:
        {"signature": one of \
        ["stacked-form","full-width-grid","left-list-right-detail","two-parallel-columns"], \
        "workflow": one of \
        ["order-entry","results-review","problem-list","med-reconciliation"], \
        "regions": [{"element": one of \
        ["title-bar","section-header","data-grid","input-field-stack","list-column",\
        "detail-card","comparison-column","primary-button"], \
        "x": 0..1, "y": 0..1, "w": 0..1, "h": 0..1, "confidence": 0..1}]}
        Coordinates are normalized to the window, origin top-left.
        HARD RULES: describe STRUCTURE and PURPOSE only. Do NOT transcribe or read
        any text. Do NOT report any patient name, MRN, number, date, dose, lab
        value, or any content. No PHI. Output JSON only.
        """

    /// The localhost request body. `base64Frame` is produced and consumed only on
    /// the clinician's machine at runtime; it is never persisted or transmitted
    /// off-device.
    static func requestBody(base64Frame: String, prompt: String = regionPrompt) -> Data {
        let payload: [String: Any] = [
            "model": visionModel,
            "prompt": prompt,
            "images": [base64Frame],
            "stream": false,
            "options": ["temperature": 0.1, "num_predict": 512],
        ]
        return (try? JSONSerialization.data(withJSONObject: payload)) ?? Data()
    }

    /// The model reply shape (Ollama wraps the model text in `response`).
    private struct Envelope: Decodable { let response: String }
    private struct RawRegion: Decodable {
        let element: String
        let x: Double
        let y: Double
        let w: Double
        let h: Double
        let confidence: Double?
    }
    private struct RawReadout: Decodable {
        let signature: String
        let workflow: String
        let regions: [RawRegion]
    }

    /// Parse the model's JSON reply into a clamped `ScreenReadout`. Unknown
    /// element/signature/workflow tokens fail closed (dropped or defaulted) so a
    /// malformed reply can never inject an out-of-vocabulary label.
    static func parseReadout(
        from responseData: Data,
        windowWidth: Int,
        windowHeight: Int
    ) -> ScreenReadout? {
        let decoder = JSONDecoder()
        let jsonText: String
        if let envelope = try? decoder.decode(Envelope.self, from: responseData) {
            jsonText = envelope.response
        } else if let text = String(data: responseData, encoding: .utf8) {
            jsonText = text
        } else {
            return nil
        }
        guard let start = jsonText.firstIndex(of: "{"),
              let end = jsonText.lastIndex(of: "}"),
              let raw = try? decoder.decode(
                  RawReadout.self,
                  from: Data(jsonText[start...end].utf8)
              ),
              let signature = ScreenLayoutSignature(rawValue: raw.signature),
              let workflow = WorkflowTag(rawValue: raw.workflow) else {
            return nil
        }
        let regions: [ScreenRegion] = raw.regions.enumerated().compactMap { index, item in
            guard let element = ScreenElementKind(rawValue: item.element) else { return nil }
            return ScreenRegion(
                id: "region-\(index)",
                element: element,
                normalizedRect: NormalizedRect(x: item.x, y: item.y, width: item.w, height: item.h),
                confidence: item.confidence ?? 0.5
            )
        }
        return ScreenReadout(
            windowWidth: windowWidth,
            windowHeight: windowHeight,
            signature: signature,
            workflow: workflow,
            regions: regions
        )
    }
}
