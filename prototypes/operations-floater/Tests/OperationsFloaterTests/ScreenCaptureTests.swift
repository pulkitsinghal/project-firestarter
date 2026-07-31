import CoreGraphics
import Foundation
import Testing
@testable import OperationsFloater

// These tests exercise the REAL capture wiring — window suggestion, downscale
// geometry, frame encoding, and the capture controller's state machine — using
// only SYNTHETIC inputs. No real window is ever enumerated or captured, so the
// path is fully verified with zero screen access and zero PHI.

private func candidate(
    id: CGWindowID,
    app: String,
    bundle: String?,
    title: String = "",
    width: Int = 1_200,
    height: Int = 800
) -> CaptureCandidateWindow {
    CaptureCandidateWindow(
        id: id,
        applicationName: app,
        bundleIdentifier: bundle,
        title: title,
        width: width,
        height: height,
        isCitrixViewer: CitrixWindowHeuristic.isCitrix(
            applicationName: app,
            bundleIdentifier: bundle
        )
    )
}

@Suite("Citrix window auto-suggest")
struct CitrixWindowHeuristicTests {
    @Test("Recognizes Citrix Viewer by bundle id and exact name")
    func recognizesCitrix() {
        #expect(CitrixWindowHeuristic.isCitrix(
            applicationName: "Citrix Viewer",
            bundleIdentifier: "com.citrix.receiver.icaviewer.mac"))
        #expect(CitrixWindowHeuristic.isCitrix(
            applicationName: "Citrix Viewer", bundleIdentifier: nil))
        #expect(CitrixWindowHeuristic.isCitrix(
            applicationName: "Some Window", bundleIdentifier: "com.citrix.foo"))
    }

    @Test("Does not mislabel ordinary apps as Citrix")
    func rejectsNonCitrix() {
        #expect(!CitrixWindowHeuristic.isCitrix(
            applicationName: "Safari", bundleIdentifier: "com.apple.Safari"))
        #expect(!CitrixWindowHeuristic.isCitrix(
            applicationName: "Notes", bundleIdentifier: "com.apple.Notes"))
        // A short "ica" substring alone must not trip the name fallback.
        #expect(!CitrixWindowHeuristic.isCitrix(
            applicationName: "Jamaica Weather", bundleIdentifier: "com.example.weather"))
    }

    @Test("Suggests the largest Citrix window and ranks Citrix first")
    func suggestsAndRanks() {
        let windows = [
            candidate(id: 1, app: "Safari", bundle: "com.apple.Safari", width: 1_600, height: 1_000),
            candidate(id: 2, app: "Citrix Viewer", bundle: "com.citrix.receiver.icaviewer.mac",
                      width: 900, height: 700),
            candidate(id: 3, app: "Citrix Viewer", bundle: "com.citrix.receiver.icaviewer.mac",
                      width: 1_400, height: 900),
        ]
        let suggested = CitrixWindowHeuristic.suggested(from: windows)
        #expect(suggested?.id == 3)  // the larger Citrix window

        let ranked = CitrixWindowHeuristic.ranked(windows)
        #expect(ranked.first?.isCitrixViewer == true)
        #expect(ranked.first?.id == 3)
        #expect(ranked.last?.id == 1)  // the non-Citrix (largest) app sinks below Citrix
    }

    @Test("Returns nil suggestion when no Citrix window is present")
    func noCitrix() {
        let windows = [candidate(id: 1, app: "Safari", bundle: "com.apple.Safari")]
        #expect(CitrixWindowHeuristic.suggested(from: windows) == nil)
    }
}

@Suite("Frame downscale geometry")
struct FrameDownscaleTests {
    @Test("Caps the longest edge and preserves aspect ratio")
    func capsLongestEdge() {
        let (w, h) = FrameDownscale.targetSize(
            sourceWidth: 2_200, sourceHeight: 1_400, maxDimension: 1_400)
        #expect(w == 1_400)
        #expect(h == 891)  // 1400/2200 * 1400 = 890.9 -> 891
    }

    @Test("Never upscales a frame already within bounds")
    func noUpscale() {
        let (w, h) = FrameDownscale.targetSize(
            sourceWidth: 800, sourceHeight: 600, maxDimension: 1_400)
        #expect(w == 800)
        #expect(h == 600)
    }

    @Test("Degenerate input is clamped, never zero")
    func degenerate() {
        let (w, h) = FrameDownscale.targetSize(
            sourceWidth: 0, sourceHeight: 0, maxDimension: 1_400)
        #expect(w >= 1 && h >= 1)
    }
}

@Suite("Synthetic frame + encoding")
struct FrameEncoderTests {
    @Test("Synthetic results-grid renders at the requested content-free size")
    func syntheticFrameRenders() throws {
        let image = try #require(SyntheticCaptureFrame.resultsGrid(width: 640, height: 400))
        #expect(image.width == 640)
        #expect(image.height == 400)
    }

    @Test("JPEG/base64 encode of a synthetic frame decodes back to a JPEG")
    func encodesSyntheticFrame() throws {
        let image = try #require(SyntheticCaptureFrame.resultsGrid(width: 320, height: 200))
        let base64 = try #require(FrameEncoder.base64JPEG(image))
        #expect(!base64.isEmpty)
        let data = try #require(Data(base64Encoded: base64))
        // JPEG SOI magic bytes 0xFF 0xD8.
        #expect(data.count > 2)
        #expect(data[0] == 0xFF)
        #expect(data[1] == 0xD8)
    }
}

private final class ReadoutBox: @unchecked Sendable {
    var readout: ScreenReadout?
}

@Suite("Screen capture controller state machine")
@MainActor
struct ScreenCaptureControllerTests {
    private func fixedReadout() -> ScreenReadout {
        SyntheticScreenTrainerModel.readout(for: .resultsReview)
    }

    @Test("Auto-captures the suggested Citrix window and delivers the model read")
    func autoCapturesCitrix() async {
        let box = ReadoutBox()
        let expected = fixedReadout()
        let controller = ScreenCaptureController(
            deliver: { box.readout = $0 },
            listWindows: {
                [candidate(id: 7, app: "Citrix Viewer",
                           bundle: "com.citrix.receiver.icaviewer.mac")]
            },
            capture: { _ in ("QUJD", 1_100, 760) },
            read: { _, _, _ in expected }
        )
        await controller.performBeginCapture()
        #expect(box.readout == expected)
        if case .done = controller.phase {} else {
            Issue.record("expected .done, got \(controller.phase)")
        }
        #expect(controller.lastLatencyText != nil)
    }

    @Test("Presents a chooser when no Citrix window is found")
    func presentsChooser() async {
        let controller = ScreenCaptureController(
            deliver: { _ in },
            listWindows: {
                [candidate(id: 1, app: "Safari", bundle: "com.apple.Safari")]
            },
            capture: { _ in ("QUJD", 10, 10) },
            read: { _, _, _ in SyntheticScreenTrainerModel.readout(for: .orderEntry) }
        )
        await controller.performBeginCapture()
        if case .choosing(let windows) = controller.phase {
            #expect(windows.count == 1)
        } else {
            Issue.record("expected .choosing, got \(controller.phase)")
        }
    }

    @Test("Capture failure surfaces a failed phase and delivers nothing")
    func captureFailureSurfaces() async {
        let box = ReadoutBox()
        let controller = ScreenCaptureController(
            deliver: { box.readout = $0 },
            listWindows: { [] },
            capture: { _ in throw ScreenCaptureService.CaptureError.windowUnavailable },
            read: { _, _, _ in SyntheticScreenTrainerModel.readout(for: .orderEntry) }
        )
        await controller.run(
            candidate(id: 2, app: "Citrix Viewer",
                      bundle: "com.citrix.receiver.icaviewer.mac"))
        #expect(box.readout == nil)
        if case .failed = controller.phase {} else {
            Issue.record("expected .failed, got \(controller.phase)")
        }
    }
}

@Suite("Live readout replaces the synthetic default")
@MainActor
struct LiveReadoutTests {
    @Test("applyLiveReadout swaps the readout, clears selection, narrates, persists nothing")
    func applyLiveReadout() {
        let session = ScreenTrainerSession(
            readout: SyntheticScreenTrainerModel.readout(for: .resultsReview),
            store: nil,
            clock: { Date(timeIntervalSince1970: 1_753_900_000) }
        )
        session.select(session.readout.regions.first?.id)
        #expect(session.selectedRegionID != nil)

        let live = SyntheticScreenTrainerModel.readout(for: .medReconciliation)
        session.applyLiveReadout(live)

        #expect(session.readout.workflow == .medReconciliation)
        #expect(session.selectedRegionID == nil)
        #expect(session.learningEvents.count == 1)
        // A read is not a taught correction — the store stays empty.
        #expect(session.corrections.isEmpty)
    }
}
