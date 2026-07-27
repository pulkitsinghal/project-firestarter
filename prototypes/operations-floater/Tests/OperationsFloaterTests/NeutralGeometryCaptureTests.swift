import CoreGraphics
import Foundation
import Testing
@testable import OperationsFloater

@Suite("Selected-window relative XY capture")
struct NeutralGeometryCaptureTests {
    private let bounds = CGRect(x: 100, y: 200, width: 400, height: 300)

    @Test("Pointer geometry is normalized to the selected window")
    @MainActor
    func normalizesPointer() throws {
        let raw = NeutralGeometryRawEvent(
            kind: .pointer(.move, 0),
            location: CGPoint(x: 300, y: 275),
            timestampNanoseconds: 100
        )
        let event = try #require(
            NeutralGeometryCaptureSession.makeEvent(
                from: raw,
                bounds: bounds,
                pointerIsTopmost: true,
                keyWindowIsActive: false
            )
        )
        #expect(event.kind == .normalizedPointer)
        #expect(event.normalizedX == 0.5)
        #expect(event.normalizedY == 0.25)
        #expect(event.buttonNumber == 0)
    }

    @Test("Pointer events outside the selected topmost window are ignored")
    @MainActor
    func ignoresOtherWindows() {
        let raw = NeutralGeometryRawEvent(
            kind: .pointer(.down, 0),
            location: CGPoint(x: 300, y: 275),
            timestampNanoseconds: 100
        )
        #expect(
            NeutralGeometryCaptureSession.makeEvent(
                from: raw,
                bounds: bounds,
                pointerIsTopmost: false,
                keyWindowIsActive: true
            ) == nil
        )
    }

    @Test("Every key is represented as code, phase, modifiers, and timing")
    @MainActor
    func capturesKeyCodeWithoutCharacters() throws {
        let raw = NeutralGeometryRawEvent(
            kind: .key(.down, 49, 1 << 17),
            location: nil,
            timestampNanoseconds: 100
        )
        let event = try #require(
            NeutralGeometryCaptureSession.makeEvent(
                from: raw,
                bounds: bounds,
                pointerIsTopmost: false,
                keyWindowIsActive: true,
                elapsedMilliseconds: 234
            )
        )
        #expect(event.kind == .rawKeyboard)
        #expect(event.keyPhase == .down)
        #expect(event.keyCode == 49)
        #expect(event.modifierFlags == 1 << 17)
        #expect(event.elapsedMilliseconds == 234)
        #expect(event.navigationKey == nil)
        #expect(event.placeholder == nil)
    }

    @Test("Keys from any other active window are ignored")
    @MainActor
    func ignoresOtherWindowKeys() {
        let raw = NeutralGeometryRawEvent(
            kind: .key(.up, 12, 0),
            location: nil,
            timestampNanoseconds: 100
        )
        #expect(
            NeutralGeometryCaptureSession.makeEvent(
                from: raw,
                bounds: bounds,
                pointerIsTopmost: true,
                keyWindowIsActive: false
            ) == nil
        )
    }

    @Test("Scroll preserves normalized location and bounded deltas")
    @MainActor
    func capturesScroll() throws {
        let raw = NeutralGeometryRawEvent(
            kind: .scroll(2.5, -7.25),
            location: CGPoint(x: 140, y: 470),
            timestampNanoseconds: 100
        )
        let event = try #require(
            NeutralGeometryCaptureSession.makeEvent(
                from: raw,
                bounds: bounds,
                pointerIsTopmost: true,
                keyWindowIsActive: false
            )
        )
        #expect(event.kind == .scroll)
        #expect(event.normalizedX == 0.1)
        #expect(event.normalizedY == 0.9)
        #expect(event.scrollDeltaX == 2.5)
        #expect(event.scrollDeltaY == -7.25)
    }
}
