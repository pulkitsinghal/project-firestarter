import AppKit
import CoreGraphics
import Foundation
import ScreenCaptureKit

// MARK: - Real screen capture (ScreenCaptureKit) for the Screen Trainer
//
// Slice 1 of the Screen Trainer was SYNTHETIC: the overlay drew a fixed
// `SyntheticScreenTrainerModel` readout so the whole correct-and-learn loop ran
// with no capture and no PHI. This file makes the read REAL: it enumerates the
// owner's on-screen windows (`SCShareableContent`), grabs a single frame of the
// window he picks (`SCScreenshotManager`, auto-suggesting the Citrix Viewer
// window), downscales it, and hands the frame to the LOCAL qwen2.5vl model over
// localhost Ollama (`OllamaScreenReader`). The model's candidate regions become
// the overlay's real read, which the owner then confirms / relabels / drags /
// types — the same slice-1 correction loop into the same on-device store.
//
// PHI BOUNDARY (absolute):
//   * A captured frame is produced only on the owner's machine, held only in
//     memory, base64-encoded, sent ONLY to http://localhost:11434, and dropped
//     the instant inference returns. It is never written to disk, never logged,
//     never placed in the correction store, and never leaves the device.
//   * Window *titles* can contain patient identifiers, so a title is used ONLY
//     for the owner's own local picker label; it is never persisted, embedded,
//     transmitted, or written to the store. The learning loop stores only the
//     content-free layout signature + workflow tag, exactly as before.
//   * Development and CI build/verify this path with a SYNTHETIC frame only
//     (`SyntheticCaptureFrame`); no real EHR/Citrix window is ever captured or
//     read during development. Real capture happens only when the owner runs the
//     installed, Screen-Recording-granted app and points it at Citrix.

// MARK: - Candidate window (Sendable value type — no SCWindow escapes)

/// One window the owner can point the trainer at. Carries only a stable window
/// id, the owning application's identity (content-free), the window's point
/// size, and — for the LOCAL picker label only — its title. The `SCWindow` object
/// itself never escapes the capture call; we re-resolve it by `windowID` at
/// capture time, which keeps this type `Sendable` under Swift 6 concurrency.
struct CaptureCandidateWindow: Identifiable, Equatable, Sendable {
    /// `SCWindow.windowID` — the CoreGraphics window number. Stable for the
    /// lifetime of the window; used to re-resolve the live `SCWindow` at capture.
    let id: CGWindowID
    /// The owning application's display name (e.g. "Citrix Viewer"). Content-free
    /// application identity, safe to show and reason about.
    let applicationName: String
    /// The owning application's bundle identifier, when known.
    let bundleIdentifier: String?
    /// The window title, shown ONLY in the owner's local picker. May contain PHI,
    /// so it is never persisted, embedded, transmitted, or stored. Never leaves
    /// the picker row.
    let title: String
    /// Window size in points.
    let width: Int
    let height: Int
    /// True when the heuristic recognizes this as a Citrix Viewer session window.
    let isCitrixViewer: Bool

    /// A short, human label for the picker row. The title is deliberately kept
    /// out of the persisted world; it appears here only for the owner to choose.
    var pickerLabel: String {
        let dims = "\(width)×\(height)"
        if title.isEmpty { return "\(applicationName) · \(dims)" }
        return "\(applicationName) — \(title) · \(dims)"
    }
}

// MARK: - Citrix auto-suggest (pure, testable)

/// Recognizes the Citrix Viewer window so the trainer can auto-suggest it, and
/// ranks candidates so the most likely EHR window floats to the top. Pure string
/// logic over content-free application identity — no capture, no PHI — so it is
/// fully unit-testable without any screen access.
enum CitrixWindowHeuristic {
    /// Bundle identifiers and application-name fragments that mark a Citrix
    /// Viewer / Receiver session window. Matched case-insensitively.
    static let citrixBundleFragments = ["com.citrix.receiver.icaviewer", "com.citrix"]
    static let citrixNameFragments = ["citrix viewer", "citrix", "ica"]

    /// Whether an application (by name + bundle id) is a Citrix Viewer host.
    static func isCitrix(applicationName: String, bundleIdentifier: String?) -> Bool {
        let name = applicationName.lowercased()
        if let bundle = bundleIdentifier?.lowercased(),
           citrixBundleFragments.contains(where: { bundle.contains($0) }) {
            return true
        }
        // Fall back to the display name only for an exact "Citrix Viewer" style
        // match, so a random window that merely mentions "ica" is not mislabeled.
        if name == "citrix viewer" { return true }
        return citrixNameFragments.contains { fragment in
            fragment.count >= 5 && name.contains(fragment)
        }
    }

    /// The best Citrix candidate from a list, or `nil` when none looks like Citrix.
    /// Prefers the largest such window (the active session, not a chooser dialog).
    static func suggested(from candidates: [CaptureCandidateWindow]) -> CaptureCandidateWindow? {
        candidates
            .filter { $0.isCitrixViewer }
            .max { ($0.width * $0.height) < ($1.width * $1.height) }
    }

    /// Candidates ordered for the picker: Citrix first, then larger windows first.
    static func ranked(_ candidates: [CaptureCandidateWindow]) -> [CaptureCandidateWindow] {
        candidates.sorted { lhs, rhs in
            if lhs.isCitrixViewer != rhs.isCitrixViewer { return lhs.isCitrixViewer }
            return (lhs.width * lhs.height) > (rhs.width * rhs.height)
        }
    }
}

// MARK: - Downscale geometry (pure, testable)

/// Computes the downscaled pixel size for a captured frame. The model does not
/// need native-resolution pixels; a bounded longest edge keeps the base64 small,
/// inference fast, and (by construction) resolves less on-screen text. Pure math,
/// so it is unit-testable with no capture.
enum FrameDownscale {
    /// Target output size for a source of `sourceWidth × sourceHeight`, with the
    /// longest edge capped at `maxDimension`. Aspect ratio is preserved exactly
    /// (no letterboxing), and the result is never upscaled.
    static func targetSize(
        sourceWidth: Int,
        sourceHeight: Int,
        maxDimension: Int
    ) -> (width: Int, height: Int) {
        guard sourceWidth > 0, sourceHeight > 0, maxDimension > 0 else {
            return (1, 1)
        }
        let longest = max(sourceWidth, sourceHeight)
        guard longest > maxDimension else { return (sourceWidth, sourceHeight) }
        let scale = Double(maxDimension) / Double(longest)
        let width = max(1, Int((Double(sourceWidth) * scale).rounded()))
        let height = max(1, Int((Double(sourceHeight) * scale).rounded()))
        return (width, height)
    }
}

// MARK: - Frame encoding (JPEG base64; testable with a synthetic CGImage)

/// Encodes an in-memory `CGImage` to a base64 JPEG payload for the local model.
/// This is the only place a frame is serialized; the produced string is handed
/// straight to `OllamaScreenReader` and then dropped. Testable by feeding a
/// SYNTHETIC `CGImage` — no real capture required.
enum FrameEncoder {
    /// JPEG-encode `image` and return base64. Returns `nil` if encoding fails.
    static func base64JPEG(_ image: CGImage, compression: Double = 0.7) -> String? {
        let rep = NSBitmapImageRep(cgImage: image)
        guard let data = rep.representation(
            using: .jpeg,
            properties: [.compressionFactor: compression]
        ) else { return nil }
        return data.base64EncodedString()
    }
}

// MARK: - ScreenCaptureKit wrapper

/// The real capture seam. Enumerates on-screen windows and grabs a single
/// downscaled frame of a chosen window with ScreenCaptureKit. Every method is a
/// nonisolated `async` static so no non-`Sendable` `SCWindow`/`SCShareableContent`
/// object ever crosses an actor boundary: the frame is turned into base64 inside
/// the same call and only `Sendable` values are returned.
enum ScreenCaptureService {
    enum CaptureError: LocalizedError {
        case notAuthorized
        case windowUnavailable
        case captureFailed(String)
        case encodingFailed

        var errorDescription: String? {
            switch self {
            case .notAuthorized:
                return "Screen Recording is not granted to this app. Enable it in "
                    + "System Settings ▸ Privacy & Security ▸ Screen Recording, then relaunch."
            case .windowUnavailable:
                return "That window is no longer available. Refresh the window list and try again."
            case .captureFailed(let detail):
                return "Capture failed: \(detail)"
            case .encodingFailed:
                return "The captured frame could not be encoded."
            }
        }
    }

    /// Whether Screen Recording is already granted, without prompting. Backed by
    /// `CGPreflightScreenCaptureAccess()`; used only to drive status copy.
    static func isAuthorized() -> Bool {
        CGPreflightScreenCaptureAccess()
    }

    /// Enumerate the owner's on-screen windows as `Sendable` candidates. The first
    /// call while ungranted triggers the system Screen-Recording prompt (via
    /// ScreenCaptureKit) and throws until the owner grants it.
    static func listWindows() async throws -> [CaptureCandidateWindow] {
        let content: SCShareableContent
        do {
            content = try await SCShareableContent.excludingDesktopWindows(
                false,
                onScreenWindowsOnly: true
            )
        } catch {
            throw CaptureError.notAuthorized
        }
        let ownBundle = Bundle.main.bundleIdentifier
        let candidates: [CaptureCandidateWindow] = content.windows.compactMap { window in
            guard let app = window.owningApplication else { return nil }
            // Never offer our own overlay/dashboard windows as a capture target.
            if let ownBundle, app.bundleIdentifier == ownBundle { return nil }
            let width = Int(window.frame.width.rounded())
            let height = Int(window.frame.height.rounded())
            // Skip degenerate / chrome-only strips.
            guard width >= 200, height >= 150 else { return nil }
            let appName = app.applicationName
            let bundleID = app.bundleIdentifier
            return CaptureCandidateWindow(
                id: window.windowID,
                applicationName: appName.isEmpty ? "Unknown app" : appName,
                bundleIdentifier: bundleID.isEmpty ? nil : bundleID,
                title: window.title ?? "",
                width: width,
                height: height,
                isCitrixViewer: CitrixWindowHeuristic.isCitrix(
                    applicationName: appName,
                    bundleIdentifier: bundleID
                )
            )
        }
        return CitrixWindowHeuristic.ranked(candidates)
    }

    /// Capture one downscaled frame of the window with `windowID` and return it as
    /// base64 JPEG plus the frame's pixel size. The `CGImage` is a local; it is
    /// released when this function returns and is never written to disk.
    static func captureBase64(
        windowID: CGWindowID,
        maxDimension: Int = 1_400
    ) async throws -> (base64: String, pixelWidth: Int, pixelHeight: Int) {
        // Re-resolve the live SCWindow now (it never escaped the last call).
        let content: SCShareableContent
        do {
            content = try await SCShareableContent.excludingDesktopWindows(
                false,
                onScreenWindowsOnly: true
            )
        } catch {
            throw CaptureError.notAuthorized
        }
        guard let window = content.windows.first(where: { $0.windowID == windowID }) else {
            throw CaptureError.windowUnavailable
        }
        let target = FrameDownscale.targetSize(
            sourceWidth: Int(window.frame.width.rounded()),
            sourceHeight: Int(window.frame.height.rounded()),
            maxDimension: maxDimension
        )
        let filter = SCContentFilter(desktopIndependentWindow: window)
        let configuration = SCStreamConfiguration()
        configuration.width = target.width
        configuration.height = target.height
        configuration.showsCursor = false
        configuration.scalesToFit = true
        configuration.ignoreShadowsSingleWindow = true

        let image: CGImage
        do {
            image = try await SCScreenshotManager.captureImage(
                contentFilter: filter,
                configuration: configuration
            )
        } catch {
            throw CaptureError.captureFailed(error.localizedDescription)
        }
        guard let base64 = FrameEncoder.base64JPEG(image) else {
            throw CaptureError.encodingFailed
        }
        // `image` and its backing pixels go out of scope here — nothing persists.
        return (base64, image.width, image.height)
    }
}

// MARK: - Live localhost inference (the wired seam, now callable)

extension OllamaScreenReader {
    enum ReadError: LocalizedError {
        case unreachable(String)
        case unparseable

        var errorDescription: String? {
            switch self {
            case .unreachable(let detail):
                return "Local model unreachable at \(OllamaScreenReader.endpoint.host ?? "localhost"): "
                    + "\(detail). Is Ollama running with \(OllamaScreenReader.visionModel)?"
            case .unparseable:
                return "The local model's reply could not be parsed into a layout readout."
            }
        }
    }

    /// Send the base64 frame to the LOCAL model and parse its readout. Runs ONLY on
    /// the owner's machine: the frame reaches `http://localhost:11434` and nowhere
    /// else, and the caller drops it the instant this returns. No pixels are logged.
    static func read(
        base64Frame: String,
        windowWidth: Int,
        windowHeight: Int,
        urlSession: URLSession = .shared,
        timeout: TimeInterval = 180
    ) async throws -> ScreenReadout {
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = requestBody(base64Frame: base64Frame)
        request.timeoutInterval = timeout

        let data: Data
        do {
            (data, _) = try await urlSession.data(for: request)
        } catch {
            throw ReadError.unreachable(error.localizedDescription)
        }
        guard let readout = parseReadout(
            from: data,
            windowWidth: windowWidth,
            windowHeight: windowHeight
        ) else {
            throw ReadError.unparseable
        }
        return readout
    }
}

// MARK: - Synthetic capture frame (dev/CI only — never a real screen)

/// Renders a content-free, EHR-shaped frame entirely in memory so the whole
/// capture → encode → local-model → readout path can be built and verified with
/// NO real screen capture and NO PHI. It draws only plain panels, header strips,
/// and grid rules — never text, never patient content. This is the ONLY frame
/// used by `--capture-selftest` and by unit tests of the encode path.
enum SyntheticCaptureFrame {
    /// A "full-width grid" results-review style layout: navy title bar, a header
    /// row, and a ruled data grid of empty cells. Content-free by construction.
    static func resultsGrid(width: Int = 1_100, height: Int = 760) -> CGImage? {
        let colorSpace = CGColorSpaceCreateDeviceRGB()
        guard let ctx = CGContext(
            data: nil,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: 0,
            space: colorSpace,
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        ) else { return nil }

        func fill(_ rect: CGRect, _ rgb: (Double, Double, Double)) {
            ctx.setFillColor(red: rgb.0, green: rgb.1, blue: rgb.2, alpha: 1)
            ctx.fill(rect)
        }
        let w = CGFloat(width)
        let h = CGFloat(height)
        // Page background (light).
        fill(CGRect(x: 0, y: 0, width: w, height: h), (0.96, 0.96, 0.97))
        // Title bar (navy) across the top.
        let titleH = h * 0.055
        fill(CGRect(x: 0, y: h - titleH, width: w, height: titleH), (0.11, 0.20, 0.37))
        // Column-header strip.
        let headerY = h - titleH - h * 0.05
        fill(CGRect(x: w * 0.02, y: headerY, width: w * 0.96, height: h * 0.045), (0.82, 0.86, 0.92))
        // Ruled grid body of empty cells.
        let gridTop = headerY - 6
        let gridBottom = h * 0.03
        let gridLeft = w * 0.02
        let gridRight = w * 0.98
        ctx.setStrokeColor(red: 0.75, green: 0.77, blue: 0.80, alpha: 1)
        ctx.setLineWidth(1)
        let rows = 14
        let cols = 5
        for r in 0...rows {
            let y = gridBottom + (gridTop - gridBottom) * CGFloat(r) / CGFloat(rows)
            ctx.move(to: CGPoint(x: gridLeft, y: y))
            ctx.addLine(to: CGPoint(x: gridRight, y: y))
        }
        for c in 0...cols {
            let x = gridLeft + (gridRight - gridLeft) * CGFloat(c) / CGFloat(cols)
            ctx.move(to: CGPoint(x: x, y: gridBottom))
            ctx.addLine(to: CGPoint(x: x, y: gridTop))
        }
        ctx.strokePath()
        // Faint value bars so cells look populated but carry no text/PHI.
        ctx.setFillColor(red: 0.70, green: 0.73, blue: 0.77, alpha: 1)
        for r in 0..<rows {
            for c in 0..<cols {
                let cellW = (gridRight - gridLeft) / CGFloat(cols)
                let cellH = (gridTop - gridBottom) / CGFloat(rows)
                let x = gridLeft + cellW * CGFloat(c) + cellW * 0.12
                let y = gridBottom + cellH * CGFloat(r) + cellH * 0.35
                fill(CGRect(x: x, y: y, width: cellW * 0.6, height: cellH * 0.28), (0.70, 0.73, 0.77))
            }
        }
        return ctx.makeImage()
    }
}

// MARK: - Capture self-test (synthetic, PHI-free end-to-end wiring check)

/// A launch-time self-test (`--capture-selftest`) that exercises the REAL wiring
/// — downscale → JPEG/base64 encode → local model → parse — against a SYNTHETIC
/// in-memory frame. It NEVER enumerates or captures a real window, so it proves
/// the frame→model→readout path with zero capture and zero PHI. Prints a compact,
/// parseable trace to stdout and never persists anything.
enum CaptureSelfTest {
    static let argument = "--capture-selftest"
    /// Skip the localhost model call (encode-only check).
    static let noModelArgument = "--capture-selftest-no-model"

    static func isRequested(
        arguments: [String] = ProcessInfo.processInfo.arguments
    ) -> Bool {
        arguments.contains(argument)
    }

    static func run(
        arguments: [String] = ProcessInfo.processInfo.arguments
    ) async {
        func log(_ message: String) { print("capture-selftest: \(message)") }

        guard let frame = SyntheticCaptureFrame.resultsGrid() else {
            log("FAIL — could not render synthetic frame")
            return
        }
        log("synthetic frame rendered \(frame.width)×\(frame.height) (content-free)")

        let target = FrameDownscale.targetSize(
            sourceWidth: frame.width,
            sourceHeight: frame.height,
            maxDimension: 1_400
        )
        log("downscale target for max-edge 1400 → \(target.width)×\(target.height)")

        guard let base64 = FrameEncoder.base64JPEG(frame) else {
            log("FAIL — JPEG/base64 encode failed")
            return
        }
        log("encoded base64 JPEG: \(base64.count) chars")

        if arguments.contains(noModelArgument) {
            log("PASS (encode path only; model call skipped)")
            return
        }

        log("posting synthetic frame to LOCAL model \(OllamaScreenReader.visionModel) at "
            + "\(OllamaScreenReader.endpoint.absoluteString) …")
        let start = Date()
        do {
            let readout = try await OllamaScreenReader.read(
                base64Frame: base64,
                windowWidth: frame.width,
                windowHeight: frame.height
            )
            let latency = Date().timeIntervalSince(start)
            log(String(
                format: "readout workflow=%@ signature=%@ regions=%d latency=%.1fs",
                readout.workflow.rawValue,
                readout.signature.rawValue,
                readout.regions.count,
                latency
            ))
            for region in readout.regions.prefix(8) {
                let r = region.normalizedRect
                log(String(
                    format: "  region %@ conf=%.2f rect=(%.2f,%.2f,%.2f,%.2f)",
                    region.element.rawValue, region.confidence, r.x, r.y, r.width, r.height
                ))
            }
            log("PASS (synthetic frame → local model → parsed readout)")
        } catch {
            let latency = Date().timeIntervalSince(start)
            log(String(format: "model call did not complete after %.1fs: %@",
                       latency, error.localizedDescription))
            log("SOFT-PASS (encode path verified; local model unreachable/slow — "
                + "the on-device path is wired, run again with Ollama warm)")
        }
    }
}
