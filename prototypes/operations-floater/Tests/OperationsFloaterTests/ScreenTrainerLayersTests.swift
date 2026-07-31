import CoreGraphics
import Foundation
import Testing
@testable import OperationsFloater

@Suite("Overlay layer/group model")
struct OverlayCompositionModelTests {
    private func composition() -> OverlayComposition {
        var c = OverlayComposition()
        let g = c.addGroup(name: "inpatient")  // inserted at top
        c.addLayer(label: "Open orders", normalizedRect: .init(x: 0, y: 0, width: 0.2, height: 0.1),
                   actionLaneIndex: 0, groupID: g.id)
        c.addLayer(label: "Sign", normalizedRect: .init(x: 0.5, y: 0.5, width: 0.2, height: 0.1),
                   actionLaneIndex: 1, groupID: g.id)
        return c
    }

    @Test("Authoring an overlay records label, purpose, action-lane slot, and group")
    func authorsOverlayWithAllFields() {
        var c = OverlayComposition()
        let group = c.addGroup(name: "outpatient")
        let layer = c.addLayer(
            label: "  Attach visit dx  ",
            purpose: "  Attach the visit diagnosis before checkout.  ",
            normalizedRect: .init(x: 0.2, y: 0.2, width: 0.4, height: 0.2),
            actionLaneIndex: 3,
            groupID: group.id
        )
        #expect(layer.label == "Attach visit dx")  // trimmed
        #expect(layer.purpose == "Attach the visit diagnosis before checkout.")
        #expect(layer.actionLaneIndex == 3)
        #expect(layer.groupID == group.id)
        #expect(layer.visible)
        #expect(c.layers.contains(layer))
    }

    @Test("A new overlay auto-assigns the next free action-lane slot")
    func nextActionLaneIndexIsUsedByDefault() {
        var c = OverlayComposition()
        c.addLayer(label: "a", normalizedRect: .init(x: 0, y: 0, width: 0.1, height: 0.1), actionLaneIndex: 0)
        c.addLayer(label: "b", normalizedRect: .init(x: 0, y: 0, width: 0.1, height: 0.1), actionLaneIndex: 5)
        #expect(c.nextActionLaneIndex == 6)
        let auto = c.addLayer(label: "c", normalizedRect: .init(x: 0, y: 0, width: 0.1, height: 0.1))
        #expect(auto.actionLaneIndex == 6)
    }

    @Test("Per-item visibility toggle hides just that layer")
    func perItemVisibilityToggle() {
        var c = composition()
        let target = c.layers(inGroup: c.groups[0].id).first { $0.label == "Sign" }!
        #expect(c.isEffectivelyVisible(target))
        c.toggleLayer(target.id)
        let after = c.layer(withID: target.id)!
        #expect(after.visible == false)
        #expect(!c.isEffectivelyVisible(after))
        // The sibling is unaffected.
        let sibling = c.layers.first { $0.label == "Open orders" }!
        #expect(c.isEffectivelyVisible(sibling))
    }

    @Test("Per-group visibility toggle hides every layer in the group")
    func perGroupVisibilityToggle() {
        var c = composition()
        let groupID = c.groups[0].id
        #expect(c.renderableLayers.count == 2)
        c.toggleGroup(groupID)
        // Group hidden: layers keep their own visible=true but no longer render.
        #expect(c.groups[0].visible == false)
        #expect(c.renderableLayers.isEmpty)
        for layer in c.layers(inGroup: groupID) {
            #expect(layer.visible)  // own flag untouched
            #expect(!c.isEffectivelyVisible(layer))
        }
    }

    @Test("Hidden overlays (by item or by group) are excluded from what renders")
    func hiddenOverlaysDoNotRender() {
        var c = OverlayComposition()
        let inp = c.addGroup(name: "inpatient")
        let out = c.addGroup(name: "outpatient")
        let a = c.addLayer(label: "a", normalizedRect: .init(x: 0, y: 0, width: 0.1, height: 0.1),
                           actionLaneIndex: 0, groupID: inp.id)
        let b = c.addLayer(label: "b", normalizedRect: .init(x: 0, y: 0, width: 0.1, height: 0.1),
                           actionLaneIndex: 1, groupID: inp.id, visible: false)
        let d = c.addLayer(label: "d", normalizedRect: .init(x: 0, y: 0, width: 0.1, height: 0.1),
                           actionLaneIndex: 2, groupID: out.id)

        // b is hidden by its own flag; a and d render.
        var ids = Set(c.renderableLayers.map(\.id))
        #expect(ids == [a.id, d.id])
        #expect(!ids.contains(b.id))

        // Hide the outpatient group: d drops out too, even though d.visible == true.
        c.toggleGroup(out.id)
        ids = Set(c.renderableLayers.map(\.id))
        #expect(ids == [a.id])
        #expect(c.layer(withID: d.id)!.visible)
    }

    @Test("Action-lane sequence orders layers by their workflow slot")
    func actionLaneSequenceOrders() {
        var c = OverlayComposition()
        c.addLayer(label: "third", normalizedRect: .init(x: 0, y: 0, width: 0.1, height: 0.1), actionLaneIndex: 2)
        c.addLayer(label: "first", normalizedRect: .init(x: 0, y: 0, width: 0.1, height: 0.1), actionLaneIndex: 0)
        c.addLayer(label: "second", normalizedRect: .init(x: 0, y: 0, width: 0.1, height: 0.1), actionLaneIndex: 1)
        #expect(c.actionLaneSequence.map(\.label) == ["first", "second", "third"])
    }

    @Test("Reordering a layer swaps it within its group siblings only")
    func reorderLayerWithinGroup() {
        var c = composition()
        let groupID = c.groups[0].id
        let siblings = c.layers(inGroup: groupID)
        #expect(siblings.map(\.label) == ["Open orders", "Sign"])
        c.moveLayer(siblings[1].id, by: -1)  // move "Sign" up
        #expect(c.layers(inGroup: groupID).map(\.label) == ["Sign", "Open orders"])
        // Out-of-range move is a no-op.
        c.moveLayer(siblings[1].id, by: -5)
        #expect(c.layers(inGroup: groupID).map(\.label) == ["Sign", "Open orders"])
    }

    @Test("Reordering a group moves it within the group stack")
    func reorderGroup() {
        var c = OverlayComposition()
        let a = c.addGroup(name: "a")  // stack: [a]
        let b = c.addGroup(name: "b")  // insert at top -> [b, a]
        #expect(c.groups.map(\.name) == ["b", "a"])
        c.moveGroup(a.id, by: -1)      // move a up -> [a, b]
        #expect(c.groups.map(\.name) == ["a", "b"])
        _ = b
    }

    @Test("Reassigning a layer moves it to another group; removing a group ungroups its layers")
    func regroupAndRemoveGroup() {
        var c = composition()
        let inp = c.groups[0].id
        let out = c.addGroup(name: "outpatient").id
        let layer = c.layers.first { $0.label == "Sign" }!
        c.assignLayer(layer.id, toGroup: out)
        #expect(c.layer(withID: layer.id)!.groupID == out)

        // Removing a group never deletes its layers — they become ungrouped.
        c.removeGroup(inp)
        #expect(c.group(withID: inp) == nil)
        let orphan = c.layers.first { $0.label == "Open orders" }!
        #expect(orphan.groupID == nil)
        #expect(c.isEffectivelyVisible(orphan))  // ungrouped renders on its own flag
    }

    @Test("A layer pointing at a missing group is treated as ungrouped, not hidden")
    func danglingGroupTreatedAsUngrouped() {
        var c = OverlayComposition()
        let layer = c.addLayer(label: "x", normalizedRect: .init(x: 0, y: 0, width: 0.1, height: 0.1),
                               actionLaneIndex: 0, groupID: "group-does-not-exist")
        #expect(c.isEffectivelyVisible(layer))
    }

    @Test("The starter document is well-formed and content-free")
    func starterIsWellFormed() {
        let c = OverlayComposition.starter
        #expect(c.groups.count == 2)
        #expect(c.layers.count == 4)
        #expect(c.renderableLayers.count == 4)
        for layer in c.layers {
            let rect = layer.normalizedRect
            #expect(rect.maxX <= 1.0 + 1e-9)
            #expect(rect.maxY <= 1.0 + 1e-9)
            #expect(!layer.label.isEmpty)
        }
    }
}

@Suite("Overlay composition persistence (PHI-free JSON)")
struct OverlayCompositionStoreTests {
    private func tempURL() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("overlay-composition-\(UUID().uuidString).json")
    }

    @Test("Composition round-trips through the store")
    func roundTrips() throws {
        let url = tempURL()
        defer { try? FileManager.default.removeItem(at: url) }
        let store = OverlayCompositionStore(fileURL: url)
        #expect(store.load() == nil)  // nothing saved yet

        var original = OverlayComposition()
        let group = original.addGroup(name: "inpatient")
        original.addLayer(
            label: "Sign orders",
            purpose: "Sign, then stop at the propose-confirm gate.",
            normalizedRect: .init(x: 0.3, y: 0.4, width: 0.3, height: 0.15),
            actionLaneIndex: 2,
            groupID: group.id,
            visible: false
        )
        try store.save(original)

        let loaded = try #require(store.load())
        #expect(loaded == original)
        #expect(loaded.groups.first?.name == "inpatient")
        let layer = try #require(loaded.layers.first)
        #expect(layer.label == "Sign orders")
        #expect(layer.purpose == "Sign, then stop at the propose-confirm gate.")
        #expect(layer.actionLaneIndex == 2)
        #expect(layer.visible == false)
    }

    @Test("Persisted document carries only PHI-free, author-supplied fields")
    func persistedShapeIsPHIFree() throws {
        let url = tempURL()
        defer { try? FileManager.default.removeItem(at: url) }
        let store = OverlayCompositionStore(fileURL: url)

        // The starter's expected content-free field keys are present.
        try store.save(OverlayComposition.starter)
        let starterText = try String(contentsOf: url, encoding: .utf8)
        for key in ["\"label\"", "\"purpose\"", "\"actionLaneIndex\"", "\"groupID\"", "\"visible\""] {
            #expect(starterText.contains(key))
        }

        // No PHI-shaped token is ever serialized. Neutral group/label names are used
        // here so the scan is not confused by the legitimate clinical-context names
        // "inpatient"/"outpatient" (which contain the substring "patient").
        var neutral = OverlayComposition()
        let group = neutral.addGroup(name: "context-a")
        neutral.addLayer(
            label: "step one",
            purpose: "advance the workflow",
            normalizedRect: .init(x: 0.1, y: 0.1, width: 0.2, height: 0.2),
            actionLaneIndex: 0,
            groupID: group.id
        )
        try store.save(neutral)
        let lowered = try String(contentsOf: url, encoding: .utf8).lowercased()
        for banned in ["pixel", "screenshot", "frame", "patient", "mrn", "base64", "\"image\"", "\"text\""] {
            #expect(!lowered.contains(banned))
        }
    }

    @Test("Load tolerates a corrupt document")
    func loadTolerantOfCorruption() throws {
        let url = tempURL()
        defer { try? FileManager.default.removeItem(at: url) }
        try "{ not valid json".write(to: url, atomically: true, encoding: .utf8)
        let store = OverlayCompositionStore(fileURL: url)
        #expect(store.load() == nil)
    }
}

@Suite("Overlay composition session")
struct OverlayCompositionSessionTests {
    @MainActor
    private func session(_ composition: OverlayComposition = .empty)
        -> (OverlayCompositionSession, URL)
    {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("layer-session-\(UUID().uuidString).json")
        return (
            OverlayCompositionSession(
                composition: composition,
                store: OverlayCompositionStore(fileURL: url)
            ),
            url
        )
    }

    @Test("Authoring through the session persists and selects the new overlay")
    @MainActor
    func authorPersistsAndSelects() throws {
        let (session, url) = session()
        defer { try? FileManager.default.removeItem(at: url) }
        let group = try #require(session.addGroup(name: "inpatient"))
        let layer = try #require(
            session.addOverlay(
                label: "Sign orders",
                purpose: "Sign then confirm.",
                actionLaneIndex: 4,
                groupID: group.id
            )
        )
        #expect(session.selectedLayerID == layer.id)
        #expect(session.composition.layers.count == 1)

        // Persisted: a fresh session over the same file sees the authored overlay.
        let reopened = OverlayCompositionSession(store: OverlayCompositionStore(fileURL: url))
        #expect(reopened.composition.layers.first?.label == "Sign orders")
        #expect(reopened.composition.layers.first?.actionLaneIndex == 4)
        #expect(reopened.composition.groups.first?.name == "inpatient")
    }

    @Test("Blank label or group name is rejected")
    @MainActor
    func blankInputsRejected() {
        let (session, url) = session()
        defer { try? FileManager.default.removeItem(at: url) }
        #expect(session.addOverlay(label: "   ", purpose: "x") == nil)
        #expect(session.addGroup(name: "   ") == nil)
        #expect(session.composition.layers.isEmpty)
        #expect(session.composition.groups.isEmpty)
    }

    @Test("Session visibility toggles drive what renders")
    @MainActor
    func sessionVisibilityDrivesRender() {
        let (session, url) = session(.starter)
        defer { try? FileManager.default.removeItem(at: url) }
        let before = session.renderableLayers.count
        #expect(before == 4)
        let firstGroup = session.composition.groups[0]
        session.toggleGroup(firstGroup.id)
        let hiddenInGroup = session.composition.layers(inGroup: firstGroup.id).count
        #expect(session.renderableLayers.count == before - hiddenInGroup)
    }

    @Test("A saved document overrides the seeded composition on init")
    @MainActor
    func savedDocumentWinsOverSeed() throws {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("layer-seed-\(UUID().uuidString).json")
        defer { try? FileManager.default.removeItem(at: url) }
        let store = OverlayCompositionStore(fileURL: url)
        var saved = OverlayComposition()
        saved.addGroup(name: "saved-context")
        try store.save(saved)

        // Even though we seed `.starter`, the saved document is loaded instead.
        let session = OverlayCompositionSession(composition: .starter, store: store)
        #expect(session.composition.groups.map(\.name) == ["saved-context"])
    }

    @Test("Removing the selected layer clears the selection")
    @MainActor
    func removeSelectedClearsSelection() throws {
        let (session, url) = session()
        defer { try? FileManager.default.removeItem(at: url) }
        let layer = try #require(session.addOverlay(label: "temp", purpose: ""))
        #expect(session.selectedLayerID == layer.id)
        session.removeLayer(layer.id)
        #expect(session.selectedLayerID == nil)
        #expect(session.composition.layers.isEmpty)
    }
}
