import CoreGraphics
import Foundation
import Testing
@testable import OperationsFloater

// MARK: - Fixtures (synthetic, PHI-free)

private func rect() -> NormalizedRect { .init(x: 0.1, y: 0.1, width: 0.2, height: 0.1) }

/// A tiny synthetic graph: two contexts, three nodes, two typed edges — enough to
/// exercise grouping, ordering, and relationships without any real screen or PHI.
private func sampleComposition() -> OverlayComposition {
    var c = OverlayComposition()
    let ctx = c.addGroup(name: "context-a", visible: true, id: "group-ctx")
    let a = c.addLayer(label: "Alpha tab", purpose: "start here",
                       normalizedRect: rect(), actionLaneIndex: 0, groupID: ctx.id, id: "layer-a")
    let b = c.addLayer(label: "Bravo button", purpose: "does the thing",
                       normalizedRect: rect(), actionLaneIndex: 1, groupID: ctx.id, id: "layer-b")
    let d = c.addLayer(label: "Delta panel", purpose: "",
                       normalizedRect: rect(), actionLaneIndex: 2, groupID: nil, id: "layer-d")
    c.addRelationship(from: a.id, to: b.id, kind: .houses, id: "rel-a-b")
    c.addRelationship(from: b.id, to: d.id, kind: .opens, id: "rel-b-d")
    return c
}

// MARK: - Relationship model

@Suite("Overlay relationship model")
struct OverlayRelationshipModelTests {
    @Test("Adding a relationship validates that both endpoints exist and differ")
    func addValidatesEndpoints() {
        var c = sampleComposition()
        // Missing endpoint.
        #expect(c.addRelationship(from: "layer-a", to: "layer-missing", kind: .opens) == nil)
        #expect(c.addRelationship(from: "layer-missing", to: "layer-b", kind: .opens) == nil)
        // Self-loop.
        #expect(c.addRelationship(from: "layer-a", to: "layer-a", kind: .opens) == nil)
        // Valid.
        let ok = c.addRelationship(from: "layer-d", to: "layer-a", kind: .navigatesTo)
        #expect(ok != nil)
        #expect(c.relationships.count == 3)
    }

    @Test("An identical (from,to,kind) edge is de-duplicated")
    func addDeduplicates() {
        var c = sampleComposition()
        let again = c.addRelationship(from: "layer-a", to: "layer-b", kind: .houses)
        #expect(again?.id == "rel-a-b")     // returns the existing edge
        #expect(c.relationships.count == 2) // no duplicate appended
        // A different kind between the same nodes is a distinct edge.
        _ = c.addRelationship(from: "layer-a", to: "layer-b", kind: .precedes)
        #expect(c.relationships.count == 3)
    }

    @Test("Removing and editing edges keeps the endpoints valid")
    func removeAndUpdate() {
        var c = sampleComposition()
        c.removeRelationship("rel-a-b")
        #expect(c.relationship(withID: "rel-a-b") == nil)
        #expect(c.relationships.count == 1)

        // Re-point the surviving edge; an invalid re-point is ignored.
        var edge = c.relationship(withID: "rel-b-d")!
        edge.kind = .triggers
        edge.toLayerID = "layer-a"
        c.updateRelationship(edge)
        #expect(c.relationship(withID: "rel-b-d")?.kind == .triggers)
        #expect(c.relationship(withID: "rel-b-d")?.toLayerID == "layer-a")

        var bad = c.relationship(withID: "rel-b-d")!
        bad.toLayerID = "layer-nope"
        c.updateRelationship(bad)  // rejected
        #expect(c.relationship(withID: "rel-b-d")?.toLayerID == "layer-a")
    }

    @Test("Removing a layer prunes every relationship that touched it")
    func removeLayerPrunesEdges() {
        var c = sampleComposition()  // a->b, b->d
        c.removeLayer("layer-b")
        // Both edges touched layer-b, so both are gone; no dangling endpoints remain.
        #expect(c.relationships.isEmpty)
        #expect(c.layer(withID: "layer-b") == nil)
    }

    @Test("Pruning drops edges whose endpoints no longer exist")
    func pruneDangling() {
        var c = sampleComposition()
        c.layers.removeAll { $0.id == "layer-d" }  // bypass removeLayer to leave a dangle
        #expect(c.relationships.count == 2)
        c.pruneDanglingRelationships()
        #expect(c.relationships.map(\.id) == ["rel-a-b"])
    }
}

@Suite("Relationship kind is an extensible, normalized token")
struct OverlayRelationshipKindTests {
    @Test("Normalization trims, collapses whitespace, and strips graph-breaking chars")
    func normalizes() {
        #expect(OverlayRelationshipKind(rawValue: "  houses  ").rawValue == "houses")
        #expect(OverlayRelationshipKind(rawValue: "navigates   to").rawValue == "navigates to")
        #expect(OverlayRelationshipKind(rawValue: "a|b\"c[d]").rawValue == "abcd")
        #expect(OverlayRelationshipKind(rawValue: "   ").rawValue == "related")  // empty -> fallback
    }

    @Test("Custom kinds are allowed and get a humanized display phrase")
    func customKinds() {
        let custom = OverlayRelationshipKind(rawValue: "escalatesTo")
        #expect(custom.rawValue == "escalatesTo")
        #expect(custom.displayPhrase == "escalates to")
        #expect(OverlayRelationshipKind.navigatesTo.displayPhrase == "navigates to")
        #expect(OverlayRelationshipKind.partOf.displayPhrase == "is part of")
    }

    @Test("Kind serializes as a bare JSON string")
    func codableBareString() throws {
        let data = try JSONEncoder().encode(OverlayRelationshipKind.houses)
        #expect(String(data: data, encoding: .utf8) == "\"houses\"")
        let back = try JSONDecoder().decode(OverlayRelationshipKind.self, from: data)
        #expect(back == .houses)
    }
}

// MARK: - Mermaid export

@Suite("Mermaid export is deterministic and well-shaped")
struct MermaidExportTests {
    @Test("Export is byte-for-byte deterministic")
    func deterministic() {
        let c = sampleComposition()
        #expect(c.mermaidExport() == c.mermaidExport())
        #expect(OverlayComposition.starter.mermaidExport() == OverlayComposition.starter.mermaidExport())
    }

    @Test("Export carries header, subgraphs, nodes, labeled edges, and a lane note")
    func expectedShape() {
        let text = sampleComposition().mermaidExport()
        #expect(text.hasPrefix("flowchart TD"))
        #expect(text.contains("subgraph group_ctx[\"context-a\"]"))
        #expect(text.contains("end"))
        #expect(text.contains("layer_a[\"Alpha tab\"]"))
        #expect(text.contains("layer_d[\"Delta panel\"]"))          // ungrouped node present
        #expect(text.contains("layer_a -->|houses| layer_b"))       // owner's `a tab houses b button`
        #expect(text.contains("layer_b -->|opens| layer_d"))
        #expect(text.contains("%% purpose layer_a: start here"))    // purpose carried as metadata
        #expect(text.contains("%% action-lane order:"))             // workflow order noted
    }

    @Test("Grouped nodes appear inside their subgraph, ungrouped at the top level")
    func groupedSubgraphOutput() {
        let text = sampleComposition().mermaidExport()
        let lines = text.split(separator: "\n").map(String.init)
        let subStart = lines.firstIndex(of: "subgraph group_ctx[\"context-a\"]")!
        let subEnd = lines[subStart...].firstIndex(of: "end")!
        let inside = lines[(subStart + 1)..<subEnd]
        #expect(inside.contains("  layer_a[\"Alpha tab\"]"))
        #expect(inside.contains("  layer_b[\"Bravo button\"]"))
        #expect(!inside.contains { $0.contains("layer_d") })  // Delta is ungrouped
    }
}

// MARK: - Mermaid import + round-trip

@Suite("Mermaid import round-trips and merges edits")
struct MermaidImportTests {
    @Test("export -> import -> export is stable, and merge-onto-self is the identity")
    func roundTripStable() throws {
        for c in [sampleComposition(), OverlayComposition.starter] {
            let m1 = c.mermaidExport()
            let result = c.applyingMermaid(m1)
            guard case .success(let c2) = result else {
                Issue.record("import failed: \(result)")
                continue
            }
            #expect(c2.mermaidExport() == m1)  // textual stability
            #expect(c2 == c)                   // merge onto self is a no-op
        }
    }

    @Test("Importing into an empty model reconstructs nodes, groups, and edges")
    func importIntoEmpty() throws {
        let source = sampleComposition()
        let m1 = source.mermaidExport()
        guard case .success(let fresh) = OverlayComposition.empty.applyingMermaid(m1) else {
            Issue.record("import failed"); return
        }
        #expect(fresh.layers.count == 3)
        #expect(fresh.groups.count == 1)
        #expect(fresh.relationships.count == 2)
        #expect(Set(fresh.layers.map(\.label)) == ["Alpha tab", "Bravo button", "Delta panel"])
        #expect(Set(fresh.relationships.map(\.kind.rawValue)) == ["houses", "opens"])
        #expect(fresh.groups.first?.name == "context-a")
    }

    @Test("Editing the mermaid renames a node, re-groups it, and edits edges")
    func editsApply() throws {
        // The owner's canonical example, hand-written: `a tab houses a button`.
        let text = """
        flowchart TD
        subgraph ctx_one["Orders"]
          tab["Orders tab"]
          btn["Sign button"]
        end
        tab -->|houses| btn
        """
        guard case .success(let c) = OverlayComposition.empty.applyingMermaid(text) else {
            Issue.record("import failed"); return
        }
        #expect(c.layers.count == 2)
        #expect(c.groups.map(\.name) == ["Orders"])
        let tab = c.layers.first { $0.label == "Orders tab" }!
        let btn = c.layers.first { $0.label == "Sign button" }!
        #expect(c.group(for: tab)?.name == "Orders")
        #expect(c.group(for: btn)?.name == "Orders")
        let edge = try #require(c.relationships.first)
        #expect(edge.fromLayerID == tab.id)
        #expect(edge.toLayerID == btn.id)
        #expect(edge.kind == .houses)
    }

    @Test("Adding and removing edge lines adds and removes relationships")
    func addAndRemoveEdges() throws {
        let c = sampleComposition()
        // Add an edge line.
        let added = c.mermaidExport() + "layer_a -->|precedes| layer_d\n"
        guard case .success(let withEdge) = c.applyingMermaid(added) else {
            Issue.record("add failed"); return
        }
        #expect(withEdge.relationships.count == 3)
        #expect(withEdge.relationships.contains {
            $0.fromLayerID == "layer-a" && $0.toLayerID == "layer-d" && $0.kind == .precedes
        })

        // Remove one edge line (the b->d "opens" edge) from the exported text.
        let pruned = c.mermaidExport()
            .split(separator: "\n")
            .filter { $0 != "layer_b -->|opens| layer_d" }
            .joined(separator: "\n")
        guard case .success(let withoutEdge) = c.applyingMermaid(pruned) else {
            Issue.record("remove failed"); return
        }
        #expect(withoutEdge.relationships.map(\.id) == ["rel-a-b"])
    }

    @Test("Visibility (layer + group hidden) round-trips through mermaid")
    func visibilityRoundTrips() throws {
        var c = OverlayComposition.starter
        c.toggleLayer("layer-sign")
        c.toggleGroup("group-outpatient")
        let text = c.mermaidExport()
        #expect(text.contains("%% hidden layer_sign"))
        #expect(text.contains("%% group-hidden group_outpatient"))
        guard case .success(let c2) = c.applyingMermaid(text) else {
            Issue.record("import failed"); return
        }
        #expect(c2.layer(withID: "layer-sign")?.visible == false)
        #expect(c2.group(withID: "group-outpatient")?.visible == false)
        #expect(c2 == c)
    }
}

// MARK: - Malformed input fails safe

@Suite("Malformed mermaid fails safe without corrupting state")
struct MermaidFailSafeTests {
    @Test("Specific parse errors are reported and the model is never mutated")
    func failuresAreClassified() {
        let base = sampleComposition()

        // Empty / whitespace.
        #expect(base.applyingMermaid("") == .failure(.empty))
        #expect(base.applyingMermaid("   \n  ") == .failure(.empty))

        // Missing header.
        if case .failure(let e) = base.applyingMermaid("tab --> button") {
            #expect(e == .notAGraph)
        } else { Issue.record("expected notAGraph") }

        // Malformed edge (no target).
        if case .failure(let e) = base.applyingMermaid("flowchart TD\na -->") {
            #expect(e == .malformedEdge("a -->"))
        } else { Issue.record("expected malformedEdge") }

        // Unbalanced subgraph (no matching end).
        if case .failure(let e) = base.applyingMermaid("flowchart TD\nsubgraph g[\"x\"]\nn[\"N\"]") {
            #expect(e == .unbalancedSubgraph)
        } else { Issue.record("expected unbalancedSubgraph") }

        // Stray `end`.
        if case .failure(let e) = base.applyingMermaid("flowchart TD\nend") {
            #expect(e == .unbalancedSubgraph)
        } else { Issue.record("expected unbalancedSubgraph for stray end") }
    }

    @Test("A failed apply through the session leaves the composition untouched")
    @MainActor
    func sessionApplyIsFailSafe() {
        let session = OverlayCompositionSession(composition: .starter)
        let before = session.composition
        session.mermaidDraft = "this is not a graph"
        session.applyMermaid()
        #expect(session.mermaidError != nil)
        #expect(session.composition == before)  // model preserved on failure
    }

    @Test("Unmodeled directives (classDef, style, click) are ignored, not rejected")
    func ignoresUnmodeledDirectives() throws {
        let text = """
        flowchart TD
        classDef ctx fill:#eee
        n1["Node one"]
        n2["Node two"]
        n1 -->|houses| n2
        click n1 callback
        style n1 fill:#fff
        """
        guard case .success(let c) = OverlayComposition.empty.applyingMermaid(text) else {
            Issue.record("import failed"); return
        }
        #expect(c.layers.count == 2)
        #expect(c.relationships.count == 1)
    }
}

// MARK: - Persistence + PHI boundary

@Suite("Relationships persist PHI-free alongside the composition")
struct MermaidPersistenceTests {
    private func tempURL() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("mermaid-comp-\(UUID().uuidString).json")
    }

    @Test("A document with relationships round-trips through the store")
    func storeRoundTrip() throws {
        let url = tempURL()
        defer { try? FileManager.default.removeItem(at: url) }
        let store = OverlayCompositionStore(fileURL: url)
        try store.save(.starter)
        let loaded = try #require(store.load())
        #expect(loaded == .starter)
        #expect(loaded.relationships.count == 2)
        #expect(loaded.relationships.contains { $0.kind == .navigatesTo })
    }

    @Test("A pre-relationships document (no relationships key) still decodes")
    func backwardCompatibleDecode() throws {
        // Exactly the shape the layer-only slice (#72) wrote — no `relationships`.
        let json = "{\"groups\":[],\"layers\":[{\"id\":\"layer-x\",\"label\":\"X\",\"purpose\":\"\","
            + "\"normalizedRect\":{\"x\":0,\"y\":0,\"width\":0.1,\"height\":0.1},"
            + "\"actionLaneIndex\":0,\"visible\":true}]}"
        let decoded = try JSONDecoder().decode(OverlayComposition.self, from: Data(json.utf8))
        #expect(decoded.layers.count == 1)
        #expect(decoded.relationships.isEmpty)  // defaulted, not a decode failure
    }

    @Test("The serialized document carries only PHI-free relationship fields")
    func persistedShapeIsPHIFree() throws {
        let url = tempURL()
        defer { try? FileManager.default.removeItem(at: url) }
        let store = OverlayCompositionStore(fileURL: url)

        var neutral = OverlayComposition()
        let g = neutral.addGroup(name: "context-a")
        let a = neutral.addLayer(label: "step one", purpose: "advance the workflow",
                                 normalizedRect: rect(), actionLaneIndex: 0, groupID: g.id)
        let b = neutral.addLayer(label: "step two", purpose: "finish the workflow",
                                 normalizedRect: rect(), actionLaneIndex: 1, groupID: g.id)
        neutral.addRelationship(from: a.id, to: b.id, kind: .precedes)
        try store.save(neutral)

        let text = try String(contentsOf: url, encoding: .utf8)
        #expect(text.contains("\"relationships\""))
        #expect(text.contains("\"fromLayerID\""))
        #expect(text.contains("\"toLayerID\""))
        #expect(text.contains("\"kind\""))
        #expect(text.contains("\"precedes\""))  // kind is a bare string, no PHI

        let lowered = text.lowercased()
        for banned in ["pixel", "screenshot", "frame", "patient", "mrn", "base64", "\"image\"", "\"text\""] {
            #expect(!lowered.contains(banned))
        }
    }
}

// MARK: - Session bridge + statements

@Suite("What-I've-learned session bridge")
struct LearnedGraphSessionTests {
    @MainActor
    private func session(_ composition: OverlayComposition) -> (OverlayCompositionSession, URL) {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("learned-\(UUID().uuidString).json")
        return (
            OverlayCompositionSession(composition: composition,
                                      store: OverlayCompositionStore(fileURL: url)),
            url
        )
    }

    @Test("The mermaid draft mirrors the model on init and after every mutation")
    @MainActor
    func draftMirrorsModel() {
        let (session, url) = session(sampleComposition())
        defer { try? FileManager.default.removeItem(at: url) }
        #expect(session.mermaidDraft == session.composition.mermaidExport())
        _ = session.addOverlay(label: "New node", purpose: "note")
        #expect(session.mermaidDraft == session.composition.mermaidExport())
        #expect(session.mermaidDraft.contains("New node"))
    }

    @Test("Applying edited mermaid updates the model and re-canonicalizes the text")
    @MainActor
    func applySucceeds() throws {
        let (session, url) = session(sampleComposition())
        defer { try? FileManager.default.removeItem(at: url) }
        session.mermaidDraft = session.mermaidDraft
            .replacingOccurrences(of: "Bravo button", with: "Bravo control")
        session.applyMermaid()
        #expect(session.mermaidError == nil)
        #expect(session.composition.layer(withID: "layer-b")?.label == "Bravo control")
        #expect(session.mermaidDraft == session.composition.mermaidExport())
        // The change persisted.
        let reopened = OverlayCompositionSession(store: OverlayCompositionStore(fileURL: url))
        #expect(reopened.composition.layer(withID: "layer-b")?.label == "Bravo control")
    }

    @Test("Plain statements narrate edges then unconnected nodes")
    @MainActor
    func statements() {
        let (session, url) = session(sampleComposition())
        defer { try? FileManager.default.removeItem(at: url) }
        let lines = session.learnedStatements
        #expect(lines.contains("Alpha tab houses Bravo button"))
        #expect(lines.contains("Bravo button opens Delta panel"))
        // Every node here is connected, so no standalone lines.
        #expect(lines.count == 2)
    }
}
