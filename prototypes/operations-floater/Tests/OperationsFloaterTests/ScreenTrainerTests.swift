import CoreGraphics
import Foundation
import Testing
@testable import OperationsFloater

@Suite("Screen Trainer model and learning loop")
struct ScreenTrainerModelTests {
    @Test("Synthetic readout is deterministic, in-bounds, and matches the layout")
    func syntheticReadoutIsWellFormed() {
        for label in WorkflowTag.allCases {
            let readout = SyntheticScreenTrainerModel.readout(for: label)
            #expect(readout.workflow == label)
            #expect(readout.signature == label.defaultSignature)
            #expect(!readout.regions.isEmpty)
            #expect(readout.regions.contains { $0.element == .titleBar })
            for region in readout.regions {
                let rect = region.normalizedRect
                #expect(rect.x >= 0 && rect.y >= 0)
                #expect(rect.maxX <= 1.0 + 1e-9)
                #expect(rect.maxY <= 1.0 + 1e-9)
                #expect(rect.width > 0 && rect.height > 0)
                #expect(region.confidence >= 0 && region.confidence <= 1)
            }
            // Deterministic across calls.
            #expect(SyntheticScreenTrainerModel.readout(for: label) == readout)
        }
    }

    @Test("NormalizedRect clamps out-of-range input and maps to pixels")
    func normalizedRectClampsAndMaps() {
        let rect = NormalizedRect(x: -0.5, y: 0.8, width: 5, height: 5)
        #expect(rect.x == 0)
        #expect(rect.y == 0.8)
        #expect(rect.maxX <= 1.0 + 1e-9)
        #expect(rect.maxY <= 1.0 + 1e-9)

        let mid = NormalizedRect(x: 0.25, y: 0.5, width: 0.5, height: 0.25)
        let mapped = mid.cgRect(in: CGSize(width: 400, height: 200))
        #expect(mapped.origin.x == 100)
        #expect(mapped.origin.y == 100)
        #expect(mapped.width == 200)
        #expect(mapped.height == 50)
        #expect(mid.contains(CGPoint(x: 0.5, y: 0.6)))
        #expect(!mid.contains(CGPoint(x: 0.9, y: 0.6)))
    }

    @Test("Element relabel cycles through the closed vocabulary")
    func elementRelabelCycles() {
        var element = ScreenElementKind.titleBar
        var seen: Set<ScreenElementKind> = [element]
        for _ in 0..<ScreenElementKind.allCases.count {
            element = element.next
            seen.insert(element)
        }
        #expect(seen.count == ScreenElementKind.allCases.count)
        #expect(element == .titleBar)  // wraps around
    }
}

@Suite("Screen Trainer nearest-centroid memory")
struct ScreenTrainerMemoryTests {
    private func exemplar(_ label: String, _ vector: [Double]) -> LabeledEmbedding {
        LabeledEmbedding(label: label, embedding: ScreenTrainerMemory.normalize(vector))
    }

    @Test("Cosine of a normalized vector with itself is one")
    func cosineIdentity() {
        let v = ScreenTrainerMemory.normalize([0.3, 0.9, 0.1, 0.4])
        #expect(abs(ScreenTrainerMemory.cosine(v, v) - 1.0) < 1e-9)
    }

    @Test("Classify picks the nearest class centroid with a 0...1 confidence")
    func classifyPicksNearest() {
        let memory = [
            exemplar("order-entry", [1, 0, 0, 0]),
            exemplar("order-entry", [0.98, 0.05, 0, 0]),
            exemplar("results-review", [0, 1, 0, 0]),
            exemplar("results-review", [0.02, 0.99, 0, 0]),
        ]
        let centroids = ScreenTrainerMemory.centroids(memory)
        let probe = ScreenTrainerMemory.normalize([0.1, 0.95, 0, 0])
        let (label, confidence) = ScreenTrainerMemory.classify(centroids, probe)
        #expect(label == "results-review")
        #expect(confidence > 0.9 && confidence <= 1.0)

        let (emptyLabel, emptyConfidence) = ScreenTrainerMemory.classify([:], probe)
        #expect(emptyLabel == nil)
        #expect(emptyConfidence == 0)
    }

    @Test("Leave-one-out recall is perfect on separable corrections")
    func leaveOneOutSeparable() {
        let memory = [
            exemplar("a", [1, 0, 0, 0]),
            exemplar("a", [0.97, 0.1, 0, 0]),
            exemplar("b", [0, 1, 0, 0]),
            exemplar("b", [0.05, 0.98, 0, 0]),
        ]
        let (correct, scored, _) = ScreenTrainerMemory.leaveOneOutAccuracy(memory)
        #expect(scored == 4)
        #expect(correct == 4)
    }

    @Test("Leave-one-out declines to score too-small memories")
    func leaveOneOutNeedsCoverage() {
        let memory = [exemplar("a", [1, 0, 0, 0])]
        let (correct, scored, note) = ScreenTrainerMemory.leaveOneOutAccuracy(memory)
        #expect(correct == 0)
        #expect(scored == 0)
        #expect(note.contains(">=2"))
    }
}

@Suite("Screen Trainer correction store (PHI-free JSONL)")
struct ScreenTrainerCorrectionStoreTests {
    private func tempURL() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("screen-trainer-\(UUID().uuidString).jsonl")
    }

    @Test("Corrections round-trip and share the watchful_memory line shape")
    func roundTripsAndMatchesShape() throws {
        let url = tempURL()
        defer { try? FileManager.default.removeItem(at: url) }
        let store = ScreenTrainerCorrectionStore(fileURL: url)

        try store.append(
            ScreenTrainerCorrection(
                ts: "2026-07-30T12:00:00Z",
                label: "results-review",
                signature: "full-width-grid"
            )
        )
        try store.append(
            ScreenTrainerCorrection(
                ts: "2026-07-30T12:01:00Z",
                label: "order-entry",
                signature: "stacked-form",
                embedding: [0.1, 0.2, 0.3]
            )
        )

        let loaded = store.load()
        #expect(loaded.count == 2)
        #expect(loaded[0].label == "results-review")
        #expect(loaded[1].embedding == [0.1, 0.2, 0.3])

        // The persisted line carries only PHI-free keys — the same shape the
        // Python watchful_memory store reads.
        let text = try String(contentsOf: url, encoding: .utf8)
        #expect(text.contains("\"label\""))
        #expect(text.contains("\"signature\""))
        #expect(text.contains("\"ts\""))
        #expect(text.contains("\"embedding\""))
        let lowered = text.lowercased()
        for banned in ["pixel", "screenshot", "frame", "patient", "mrn", "\"text\""] {
            #expect(!lowered.contains(banned))
        }
    }

    @Test("Load tolerates blank and corrupt lines")
    func loadTolerant() throws {
        let url = tempURL()
        defer { try? FileManager.default.removeItem(at: url) }
        let good = "{\"embedding\":[],\"label\":\"a\",\"signature\":\"s\",\"ts\":\"t\"}"
        try "\n\(good)\n{not json}\n\n".write(to: url, atomically: true, encoding: .utf8)
        let store = ScreenTrainerCorrectionStore(fileURL: url)
        #expect(store.load().count == 1)
    }
}

@Suite("Screen Trainer session interaction")
struct ScreenTrainerSessionTests {
    @MainActor
    private func session() -> (ScreenTrainerSession, URL) {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("session-\(UUID().uuidString).jsonl")
        return (
            ScreenTrainerSession(
                readout: SyntheticScreenTrainerModel.readout(for: .resultsReview),
                store: ScreenTrainerCorrectionStore(fileURL: url)
            ),
            url
        )
    }

    @Test("Selecting a point picks the smallest containing region")
    @MainActor
    func selectionPicksSmallest() {
        let (session, url) = session()
        defer { try? FileManager.default.removeItem(at: url) }
        // The header band sits inside the grid's horizontal span but is smaller.
        session.selectRegion(at: CGPoint(x: 0.5, y: 0.09))
        #expect(session.selectedRegion?.element == .sectionHeader)
        session.selectRegion(at: CGPoint(x: 0.99, y: 0.99))
        #expect(session.selectedRegionID == nil || session.selectedRegion != nil)
    }

    @Test("Relabel marks the region corrected and advances the tag")
    @MainActor
    func relabelMutates() {
        let (session, url) = session()
        defer { try? FileManager.default.removeItem(at: url) }
        let grid = session.readout.regions.first { $0.element == .dataGrid }!
        session.select(grid.id)
        session.relabelSelectedElement()
        #expect(session.selectedRegion?.corrected == true)
        #expect(session.selectedRegion?.element == ScreenElementKind.dataGrid.next)
    }

    @Test("Confirming a region persists a PHI-free workflow correction")
    @MainActor
    func confirmPersists() {
        let (session, url) = session()
        defer { try? FileManager.default.removeItem(at: url) }
        let grid = session.readout.regions.first { $0.element == .dataGrid }!
        session.select(grid.id)
        session.confirmSelected()
        #expect(session.corrections.count == 1)
        #expect(session.corrections.first?.label == "results-review")
        #expect(session.corrections.first?.signature == "full-width-grid")
        #expect(session.selectedRegion?.corrected == true)
    }

    @Test("Dragging a corner resizes the selected region within bounds")
    @MainActor
    func dragCornerResizes() {
        let (session, url) = session()
        defer { try? FileManager.default.removeItem(at: url) }
        let grid = session.readout.regions.first { $0.element == .dataGrid }!
        session.select(grid.id)
        session.dragCorner(.bottomTrailing, to: CGPoint(x: 0.6, y: 0.6))
        let rect = session.selectedRegion!.normalizedRect
        #expect(abs(rect.maxX - 0.6) < 1e-9)
        #expect(abs(rect.maxY - 0.6) < 1e-9)
        #expect(session.selectedRegion?.corrected == true)
    }

    @Test("Every correction narrates one learning-feed event")
    @MainActor
    func correctionsNarrate() {
        let (session, url) = session()
        defer { try? FileManager.default.removeItem(at: url) }
        #expect(session.learningEvents.isEmpty)
        let grid = session.readout.regions.first { $0.element == .dataGrid }!
        session.select(grid.id)
        session.relabelSelectedElement()
        session.confirmSelected()
        #expect(session.learningEvents.count == 2)
        #expect(session.learningEvents.allSatisfy { $0.modality == .pointer })
        // The most recent event is last; it reflects the confirm.
        #expect(session.learningEvents.last?.summary.contains("reinforced") == true)
    }

    @Test("Typed feedback teaches the same store with a note and clears the field")
    @MainActor
    func typedFeedbackPersists() {
        let (session, url) = session()
        defer { try? FileManager.default.removeItem(at: url) }
        session.typedFeedback = "  the big grid is the results panel  "
        session.submitTypedFeedback()
        #expect(session.typedFeedback.isEmpty)
        #expect(session.corrections.count == 1)
        let correction = session.corrections[0]
        #expect(correction.modality == CorrectionModality.typed.rawValue)
        #expect(correction.note == "the big grid is the results panel")
        #expect(correction.label == "results-review")
        #expect(session.learningEvents.last?.modality == .typed)
        #expect(session.learningEvents.last?.detail == "the big grid is the results panel")

        // Empty feedback is a no-op.
        session.typedFeedback = "   "
        session.submitTypedFeedback()
        #expect(session.corrections.count == 1)
    }

    @Test("The architected voice seam routes through the one funnel")
    @MainActor
    func voiceSeamRoutesThroughFunnel() {
        let (session, url) = session()
        defer { try? FileManager.default.removeItem(at: url) }
        session.applyVoiceCorrection(
            workflow: .orderEntry,
            transcript: "this is the order entry screen"
        )
        #expect(session.readout.workflow == .orderEntry)
        #expect(session.corrections.count == 1)
        #expect(session.corrections[0].modality == CorrectionModality.voice.rawValue)
        #expect(session.corrections[0].label == "order-entry")
        #expect(session.corrections[0].note == "this is the order entry screen")
        #expect(session.learningEvents.last?.modality == .voice)
    }

    @Test("Belief line reflects accumulated reinforcement")
    @MainActor
    func beliefReflectsReinforcement() {
        let (session, url) = session()
        defer { try? FileManager.default.removeItem(at: url) }
        #expect(session.currentBelief.contains("not yet reinforced"))
        let grid = session.readout.regions.first { $0.element == .dataGrid }!
        session.select(grid.id)
        session.confirmSelected()
        session.confirmSelected()
        #expect(session.currentBelief.contains("reinforced 2×"))
        #expect(session.currentBelief.contains("results review"))
    }
}

@Suite("Screen Trainer learning ledger")
struct ScreenTrainerLedgerTests {
    @Test("Reinforcement count tallies corrections per workflow label")
    func reinforcementCount() {
        let corrections = [
            ScreenTrainerCorrection(ts: "t", label: "results-review", signature: "full-width-grid"),
            ScreenTrainerCorrection(ts: "t", label: "results-review", signature: "full-width-grid"),
            ScreenTrainerCorrection(ts: "t", label: "order-entry", signature: "stacked-form"),
        ]
        #expect(ScreenTrainerLedger.reinforcementCount(corrections, label: "results-review") == 2)
        #expect(ScreenTrainerLedger.reinforcementCount(corrections, label: "order-entry") == 1)
        #expect(ScreenTrainerLedger.reinforcementCount(corrections, label: "problem-list") == 0)
    }

    @Test("Belief text names the workflow, layout, and reinforcement")
    func beliefText() {
        let readout = SyntheticScreenTrainerModel.readout(for: .medReconciliation)
        let none = ScreenTrainerLedger.belief(for: readout, corrections: [])
        #expect(none.contains("med reconciliation"))
        #expect(none.contains("two parallel columns"))
        #expect(none.contains("not yet reinforced"))

        let taught = [
            ScreenTrainerCorrection(ts: "t", label: "med-reconciliation", signature: "two-parallel-columns")
        ]
        #expect(ScreenTrainerLedger.belief(for: readout, corrections: taught).contains("reinforced 1×"))
    }
}

@Suite("Screen Trainer live vision path wiring")
struct OllamaScreenReaderTests {
    @Test("Request body targets the local vision model with a no-PHI prompt")
    func requestBodyIsLocalAndSafe() throws {
        let data = OllamaScreenReader.requestBody(base64Frame: "QUJD")
        let json = try #require(
            try JSONSerialization.jsonObject(with: data) as? [String: Any]
        )
        #expect(json["model"] as? String == "qwen2.5vl:7b")
        #expect((json["images"] as? [String])?.first == "QUJD")
        #expect(json["stream"] as? Bool == false)
        let prompt = try #require(json["prompt"] as? String)
        #expect(prompt.contains("No PHI"))
        #expect(OllamaScreenReader.endpoint.absoluteString.contains("localhost:11434"))
    }

    @Test("Parse clamps regions and rejects out-of-vocabulary tokens")
    func parseClampsAndFailsClosed() throws {
        let reply = """
            {"response":"{\\"signature\\":\\"full-width-grid\\",\\"workflow\\":\\"results-review\\",\\"regions\\":[{\\"element\\":\\"data-grid\\",\\"x\\":0.1,\\"y\\":0.1,\\"w\\":2.0,\\"h\\":0.5,\\"confidence\\":0.9},{\\"element\\":\\"not-a-real-element\\",\\"x\\":0,\\"y\\":0,\\"w\\":1,\\"h\\":1}]}"}
            """
        let readout = try #require(
            OllamaScreenReader.parseReadout(
                from: Data(reply.utf8),
                windowWidth: 1_000,
                windowHeight: 800
            )
        )
        #expect(readout.workflow == .resultsReview)
        #expect(readout.signature == .fullWidthGrid)
        // The unknown element is dropped; the valid one is clamped into bounds.
        #expect(readout.regions.count == 1)
        #expect(readout.regions[0].normalizedRect.maxX <= 1.0 + 1e-9)

        // A reply with an out-of-vocabulary workflow fails closed.
        let bad = "{\"response\":\"{\\\"signature\\\":\\\"x\\\",\\\"workflow\\\":\\\"y\\\",\\\"regions\\\":[]}\"}"
        #expect(
            OllamaScreenReader.parseReadout(
                from: Data(bad.utf8),
                windowWidth: 100,
                windowHeight: 100
            ) == nil
        )
    }
}
