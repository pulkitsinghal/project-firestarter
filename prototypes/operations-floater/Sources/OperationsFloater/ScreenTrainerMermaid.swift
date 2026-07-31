import Foundation

// MARK: - Screen Trainer knowledge-graph: typed relationships + mermaid round-trip
//
// The layer system (`ScreenTrainerLayers.swift`, slice from #72) gives the owner the
// NODES of a semantic knowledge-graph of the EHR UI: each authored `OverlayLayer` is
// a component with a label, a purpose, an action-lane slot, and a clinical-context
// group. This file adds the EDGES — typed relationships between those nodes (a tab
// HOUSES a button, a link NAVIGATES TO a screen, an order set PRECEDES a signature) —
// and makes the whole graph expressible AND editable as mermaid text.
//
// The owner's explicit ask: "when it tells me what it's learning, that goes in a
// 'what I've learned' area — originally as a statement and as `a tab -(houses)-> b
// button` or some mermaid-metadata language I can quickly visualize and edit." So the
// composition can be rendered to mermaid, hand-edited, and imported back — a two-way
// bridge between the value model and a diagram the owner reads and edits.
//
// PHI BOUNDARY (absolute, identical to the rest of the Screen Trainer): a relationship
// carries only two layer IDs and a relationship KIND — a content-free classification
// the owner chooses. The mermaid rendering carries only the owner's labels, purposes,
// group names, and relationship kinds. No frame, no pixels, no screen text, no patient
// value ever appears here or in the exported text.

// MARK: - Relationship kind (the extensible edge vocabulary)

/// The TYPE of a relationship between two authored overlays — the edge label in the
/// knowledge graph and in the exported mermaid (`a -->|houses| b`).
///
/// Modeled as an extensible token rather than a closed enum so the clinician can coin
/// new clinical-UI relations simply by typing a new edge label in the mermaid text,
/// and those custom kinds round-trip losslessly. The static constants below are the
/// well-known vocabulary the picker offers; the set is open by design.
struct OverlayRelationshipKind: RawRepresentable, Codable, Sendable, Hashable, CustomStringConvertible {
    let rawValue: String

    init(rawValue: String) {
        self.rawValue = OverlayRelationshipKind.normalize(rawValue)
    }

    /// Normalize a coined kind to a single mermaid-safe edge token: trim, collapse
    /// internal whitespace to single spaces, and strip the characters that would break
    /// a mermaid edge label (`|`, quotes, brackets, angle brackets, newlines). A kind
    /// that normalizes to empty falls back to `related`.
    static func normalize(_ raw: String) -> String {
        let banned: Set<Character> = ["|", "\"", "[", "]", "{", "}", "<", ">", "\n", "\r", "\t"]
        let cleaned = raw.filter { !banned.contains($0) }
        let collapsed = cleaned
            .split(whereSeparator: { $0 == " " })
            .joined(separator: " ")
        return collapsed.isEmpty ? "related" : collapsed
    }

    // Well-known clinical-UI relations. OPEN vocabulary — new kinds are allowed.
    static let houses = OverlayRelationshipKind(rawValue: "houses")            // contains / holds
    static let navigatesTo = OverlayRelationshipKind(rawValue: "navigatesTo")  // links to a screen
    static let opens = OverlayRelationshipKind(rawValue: "opens")              // reveals a panel/dialog
    static let triggers = OverlayRelationshipKind(rawValue: "triggers")        // fires an action
    static let partOf = OverlayRelationshipKind(rawValue: "partOf")            // membership
    static let precedes = OverlayRelationshipKind(rawValue: "precedes")        // workflow order
    static let related = OverlayRelationshipKind(rawValue: "related")          // generic fallback

    /// The kinds the authoring UI offers by default. Not exhaustive — the owner may
    /// type any other kind into the mermaid text.
    static let wellKnown: [OverlayRelationshipKind] =
        [.houses, .navigatesTo, .opens, .triggers, .partOf, .precedes, .related]

    var description: String { rawValue }

    /// A natural-language phrase for the plain-statement view, e.g. "navigates to".
    var displayPhrase: String {
        switch self {
        case .houses: return "houses"
        case .navigatesTo: return "navigates to"
        case .opens: return "opens"
        case .triggers: return "triggers"
        case .partOf: return "is part of"
        case .precedes: return "precedes"
        case .related: return "relates to"
        default: return OverlayRelationshipKind.humanize(rawValue)
        }
    }

    /// Split a camelCase / underscored / hyphenated token into spaced lowercase words
    /// for display: `navigatesTo` -> "navigates to", `escalates_to` -> "escalates to".
    static func humanize(_ token: String) -> String {
        var words: [String] = []
        var current = ""
        for ch in token {
            if ch == "_" || ch == "-" || ch == " " {
                if !current.isEmpty { words.append(current); current = "" }
            } else if ch.isUppercase, !current.isEmpty {
                words.append(current)
                current = String(ch).lowercased()
            } else {
                current.append(ch)
            }
        }
        if !current.isEmpty { words.append(current) }
        return words.isEmpty ? token : words.joined(separator: " ")
    }

    // Codable as a bare string so the persisted document stays clean (`"kind": "houses"`).
    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        self.init(rawValue: try container.decode(String.self))
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(rawValue)
    }
}

// MARK: - Overlay relationship (one knowledge-graph edge)

/// A typed, directed edge between two authored overlays. It is the atom of the
/// knowledge-graph edge set: which node it starts at (`fromLayerID`), which it points
/// to (`toLayerID`), and WHAT the relationship is (`kind`). Content-free — only IDs
/// and a kind, persisted alongside the nodes.
struct OverlayRelationship: Identifiable, Equatable, Codable, Sendable {
    let id: String
    var fromLayerID: String
    var toLayerID: String
    var kind: OverlayRelationshipKind

    init(
        id: String = OverlayRelationship.newID(),
        fromLayerID: String,
        toLayerID: String,
        kind: OverlayRelationshipKind
    ) {
        self.id = id
        self.fromLayerID = fromLayerID
        self.toLayerID = toLayerID
        self.kind = kind
    }

    static func newID() -> String { "rel-\(UUID().uuidString.prefix(8))" }
}

// MARK: - Relationship mutations on the composition (pure value functions)

extension OverlayComposition {
    // MARK: Lookups

    func relationship(withID id: String) -> OverlayRelationship? {
        relationships.first { $0.id == id }
    }

    func relationships(from layerID: String) -> [OverlayRelationship] {
        relationships.filter { $0.fromLayerID == layerID }
    }

    func relationships(to layerID: String) -> [OverlayRelationship] {
        relationships.filter { $0.toLayerID == layerID }
    }

    func layerExists(_ id: String) -> Bool {
        layers.contains { $0.id == id }
    }

    /// Whether a relationship's two endpoints both resolve to real, distinct layers.
    func canRelate(from: String, to: String) -> Bool {
        from != to && layerExists(from) && layerExists(to)
    }

    /// Whether a relationship's endpoints both still exist (used to prune after edits).
    func endpointsExist(_ relationship: OverlayRelationship) -> Bool {
        layerExists(relationship.fromLayerID) && layerExists(relationship.toLayerID)
    }

    // MARK: Mutations (all pure — mutate this value)

    /// Add a typed edge. Validates the endpoints exist and are distinct; an identical
    /// `(from, to, kind)` edge is de-duplicated (the existing one is returned), so the
    /// graph and its deterministic export stay stable. Returns `nil` for invalid
    /// endpoints.
    @discardableResult
    mutating func addRelationship(
        from: String,
        to: String,
        kind: OverlayRelationshipKind,
        id: String = OverlayRelationship.newID()
    ) -> OverlayRelationship? {
        guard canRelate(from: from, to: to) else { return nil }
        if let existing = relationships.first(where: {
            $0.fromLayerID == from && $0.toLayerID == to && $0.kind == kind
        }) {
            return existing
        }
        let relationship = OverlayRelationship(id: id, fromLayerID: from, toLayerID: to, kind: kind)
        relationships.append(relationship)
        return relationship
    }

    /// Remove an edge by id.
    mutating func removeRelationship(_ id: String) {
        relationships.removeAll { $0.id == id }
    }

    /// Edit an existing edge (re-point or re-type it). No-op when the id is unknown or
    /// the new endpoints are invalid, so an edit can never introduce a dangling edge.
    mutating func updateRelationship(_ relationship: OverlayRelationship) {
        guard let index = relationships.firstIndex(where: { $0.id == relationship.id }) else { return }
        guard canRelate(from: relationship.fromLayerID, to: relationship.toLayerID) else { return }
        relationships[index] = relationship
    }

    /// Drop any edge whose endpoints no longer exist — the invariant restore after a
    /// bulk edit (e.g. import) or external mutation.
    mutating func pruneDanglingRelationships() {
        let liveIDs = Set(layers.map(\.id))
        relationships.removeAll { !(liveIDs.contains($0.fromLayerID) && liveIDs.contains($0.toLayerID)) }
    }

    /// Every edge in a deterministic, position-independent order: by source node
    /// token, then target node token, then kind. Used by the export and the statement
    /// view so both are stable regardless of insertion or array order.
    var orderedRelationships: [OverlayRelationship] {
        relationships.sorted { lhs, rhs in
            let lf = OverlayComposition.mermaidToken(lhs.fromLayerID)
            let rf = OverlayComposition.mermaidToken(rhs.fromLayerID)
            if lf != rf { return lf < rf }
            let lt = OverlayComposition.mermaidToken(lhs.toLayerID)
            let rt = OverlayComposition.mermaidToken(rhs.toLayerID)
            if lt != rt { return lt < rt }
            return lhs.kind.rawValue < rhs.kind.rawValue
        }
    }

    // MARK: Plain-statement narration ("what I've learned")

    /// The knowledge graph narrated as plain English statements — the "originally as a
    /// statement" half of the What-I've-learned view. One line per edge (`Open orders
    /// tab navigates to Admission order set`), then a line per node with no incident
    /// edge so authored-but-unconnected overlays are never invisible.
    var learnedStatements: [String] {
        var out: [String] = []
        for relationship in orderedRelationships {
            guard let from = layer(withID: relationship.fromLayerID),
                  let to = layer(withID: relationship.toLayerID) else { continue }
            out.append("\(from.label) \(relationship.kind.displayPhrase) \(to.label)")
        }
        let connected = Set(relationships.flatMap { [$0.fromLayerID, $0.toLayerID] })
        for layer in layers where !connected.contains(layer.id) {
            if layer.purpose.isEmpty {
                out.append(layer.label)
            } else {
                out.append("\(layer.label) — \(layer.purpose)")
            }
        }
        return out
    }
}

// MARK: - Mermaid: shared tokens + label escaping

extension OverlayComposition {
    /// The stable header the export always emits and the import requires.
    static let mermaidHeader = "flowchart TD"

    /// A mermaid-safe node / subgraph identifier derived from an internal ID. Only
    /// non-`[A-Za-z0-9_]` characters are mapped to `_`; because our IDs differ solely
    /// in their alphanumeric suffix, this is injective over a composition's IDs — which
    /// is exactly what lets import match a node back to its layer, and thus makes
    /// export -> import -> export a stable round-trip.
    static func mermaidToken(_ id: String) -> String {
        let mapped = id.map { ch -> Character in
            (ch.isLetter || ch.isNumber || ch == "_") ? ch : "_"
        }
        let token = String(mapped)
        return token.isEmpty ? "n" : token
    }

    /// Whether a string is a bare mermaid identifier: non-empty and only `[A-Za-z0-9_]`.
    static func isMermaidToken(_ s: String) -> Bool {
        !s.isEmpty && s.allSatisfy { $0.isLetter || $0.isNumber || $0 == "_" }
    }

    /// Reversibly escape a label for a mermaid `["..."]` node body. `#` is escaped
    /// first (and unescaped last) so the entity replacements can never collide with a
    /// literal `#…;` sequence in the label. For ordinary labels this is the identity.
    static func escapeLabel(_ s: String) -> String {
        var out = s.replacingOccurrences(of: "\n", with: " ")
        out = out.replacingOccurrences(of: "\r", with: " ")
        out = out.replacingOccurrences(of: "#", with: "#35;")
        out = out.replacingOccurrences(of: "\"", with: "#quot;")
        out = out.replacingOccurrences(of: "[", with: "#91;")
        out = out.replacingOccurrences(of: "]", with: "#93;")
        out = out.replacingOccurrences(of: "|", with: "#124;")
        // Escape angle brackets so a label can never spell an arrow (`-->`), which
        // would otherwise make a node line parse as an edge.
        out = out.replacingOccurrences(of: "<", with: "#60;")
        out = out.replacingOccurrences(of: ">", with: "#62;")
        return out
    }

    static func unescapeLabel(_ s: String) -> String {
        var out = s.replacingOccurrences(of: "#quot;", with: "\"")
        out = out.replacingOccurrences(of: "#91;", with: "[")
        out = out.replacingOccurrences(of: "#93;", with: "]")
        out = out.replacingOccurrences(of: "#124;", with: "|")
        out = out.replacingOccurrences(of: "#60;", with: "<")
        out = out.replacingOccurrences(of: "#62;", with: ">")
        out = out.replacingOccurrences(of: "#35;", with: "#")
        return out
    }

    /// Whether a line carries an edge arrow OUTSIDE any `[...]` label span. Used to
    /// classify a line as an edge vs a node declaration, so a label that happens to
    /// contain `-->` or `---` does not masquerade as an edge.
    static func hasEdgeArrow(_ line: String) -> Bool {
        var skeleton = ""
        var depth = 0
        for ch in line {
            if ch == "[" { depth += 1; continue }
            if ch == "]" { if depth > 0 { depth -= 1 }; continue }
            if depth == 0 { skeleton.append(ch) }
        }
        return skeleton.contains("-->") || skeleton.contains("---")
    }

    /// Collapse a purpose to a single line for a `%%` comment (comments run to EOL, so
    /// no other escaping is required).
    static func sanitizeComment(_ s: String) -> String {
        s.replacingOccurrences(of: "\n", with: " ")
            .replacingOccurrences(of: "\r", with: " ")
    }

    /// Lane-sort a set of layers deterministically: by action-lane slot, ties broken by
    /// node token (position-independent, so the order survives array reordering).
    private func laneSorted(_ list: [OverlayLayer]) -> [OverlayLayer] {
        list.sorted { a, b in
            if a.actionLaneIndex != b.actionLaneIndex { return a.actionLaneIndex < b.actionLaneIndex }
            return OverlayComposition.mermaidToken(a.id) < OverlayComposition.mermaidToken(b.id)
        }
    }
}

// MARK: - Mermaid export (deterministic, stable)

extension OverlayComposition {
    /// Render the whole composition to mermaid `flowchart` text. Nodes are authored
    /// overlays (label carried in the node body, purpose + hidden state carried as
    /// structured `%%` comments — mermaid has no native node metadata). Groups become
    /// subgraphs. Relationships become labeled edges (`a -->|houses| b`). The action-
    /// lane order is reflected both by node ordering within each subgraph and by a
    /// trailing note. Output is fully deterministic: no timestamps, no randomness, and
    /// every collection is emitted in a stable, position-independent order.
    func mermaidExport() -> String {
        var lines: [String] = []
        lines.append(OverlayComposition.mermaidHeader)
        lines.append("%% Screen Trainer knowledge graph — PHI-free: labels, purposes & relations only.")
        lines.append("%% Node = authored overlay · subgraph = clinical-context group · edge label = relationship kind.")

        func nodeLine(_ layer: OverlayLayer, indent: String) -> String {
            "\(indent)\(OverlayComposition.mermaidToken(layer.id))[\"\(OverlayComposition.escapeLabel(layer.label))\"]"
        }

        // Nodes, grouped into subgraphs in group order; each group's nodes lane-sorted.
        for group in groups {
            lines.append(
                "subgraph \(OverlayComposition.mermaidToken(group.id))[\"\(OverlayComposition.escapeLabel(group.name))\"]"
            )
            for layer in laneSorted(layers(inGroup: group.id)) {
                lines.append(nodeLine(layer, indent: "  "))
            }
            lines.append("end")
        }
        // Ungrouped nodes at the top level, lane-sorted.
        for layer in laneSorted(layers(inGroup: nil)) {
            lines.append(nodeLine(layer, indent: ""))
        }

        // Node metadata carried as structured comments so it round-trips.
        for group in groups where !group.visible {
            lines.append("%% group-hidden \(OverlayComposition.mermaidToken(group.id))")
        }
        for layer in layers.sorted(by: {
            OverlayComposition.mermaidToken($0.id) < OverlayComposition.mermaidToken($1.id)
        }) {
            let token = OverlayComposition.mermaidToken(layer.id)
            if !layer.purpose.isEmpty {
                lines.append("%% purpose \(token): \(OverlayComposition.sanitizeComment(layer.purpose))")
            }
            if !layer.visible {
                lines.append("%% hidden \(token)")
            }
        }

        // Edges, deterministically ordered.
        for relationship in orderedRelationships {
            guard let from = layer(withID: relationship.fromLayerID),
                  let to = layer(withID: relationship.toLayerID) else { continue }
            let fromToken = OverlayComposition.mermaidToken(from.id)
            let toToken = OverlayComposition.mermaidToken(to.id)
            lines.append("\(fromToken) -->|\(relationship.kind.rawValue)| \(toToken)")
        }

        // Action-lane order as a non-authoritative note (the workflow click-sequence).
        let lane = laneSorted(layers)
        if !lane.isEmpty {
            let sequence = lane.map { OverlayComposition.mermaidToken($0.id) }.joined(separator: " -> ")
            lines.append("%% action-lane order: \(sequence)")
        }

        return lines.joined(separator: "\n") + "\n"
    }
}

// MARK: - Mermaid import (fail-safe, merge onto the current model)

/// Why an edited mermaid graph could not be parsed. On any failure the model is left
/// exactly as it was — a bad edit never corrupts the authored composition.
enum OverlayMermaidError: Error, Equatable, CustomStringConvertible {
    case empty
    case notAGraph
    case unbalancedSubgraph
    case malformedEdge(String)
    case malformedNode(String)

    var description: String {
        switch self {
        case .empty:
            return "Nothing to import — the mermaid text is empty."
        case .notAGraph:
            return "Not a mermaid graph — the first line must be `flowchart TD` or `graph TD`."
        case .unbalancedSubgraph:
            return "Unbalanced subgraph — every `subgraph` needs a matching `end`."
        case .malformedEdge(let line):
            return "Could not read an edge: \"\(line)\". Expected `a -->|kind| b`."
        case .malformedNode(let line):
            return "Could not read a node: \"\(line)\". Node ids may use letters, digits, and `_`."
        }
    }
}

extension OverlayComposition {
    /// Parse an edited mermaid graph and MERGE it onto this composition, returning a
    /// new composition on success or a specific error on failure (the receiver is
    /// never mutated).
    ///
    /// Merge semantics, matching the owner's "edit the graph as text" mental model:
    /// - nodes are matched to existing layers by their token, so renames, re-grouping,
    ///   and purpose edits update in place; brand-new node ids create new layers;
    /// - existing layers keep their normalized rect and action-lane slot (geometry and
    ///   ordering are authored in the panel, not the text);
    /// - the edge set becomes exactly the edges in the text (add / remove / relabel),
    ///   with an unchanged edge keeping its id so applies don't churn.
    ///
    /// Robust to a reasonable subset of mermaid: `graph`/`flowchart` headers, quoted or
    /// bare node labels, subgraphs, `-->` / `---` edges with optional `|label|` or
    /// `-- label -->` labels, and unmodeled directives (`classDef`, `style`, `click`,
    /// `direction`, `%%{…}%%`) which are ignored rather than rejected.
    func applyingMermaid(_ text: String) -> Result<OverlayComposition, OverlayMermaidError> {
        let rawLines = text.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
        let trimmedLines = rawLines.map { $0.trimmingCharacters(in: .whitespaces) }
        guard trimmedLines.contains(where: { !$0.isEmpty }) else { return .failure(.empty) }

        // Accumulators built in a single pass.
        var orderedNodeTokens: [String] = []
        var seenNode = Set<String>()
        var nodeLabels: [String: String] = [:]
        var nodeGroupToken: [String: String?] = [:]
        var nodePurpose: [String: String] = [:]
        var nodeHidden = Set<String>()
        var groupOrder: [String] = []
        var seenGroup = Set<String>()
        var groupTitles: [String: String] = [:]
        var groupHidden = Set<String>()
        var edges: [(from: String, label: String?, to: String)] = []

        var groupStack: [String] = []
        var headerSeen = false

        // A directive we recognize as valid mermaid but do not model — ignored, so a
        // pasted graph with styling never fails to import.
        let ignoredPrefixes = ["classdef", "class ", "style ", "linkstyle", "click ", "direction ", "%%{"]

        func registerNode(token: String, label: String?) {
            if !seenNode.contains(token) {
                seenNode.insert(token)
                orderedNodeTokens.append(token)
                nodeGroupToken[token] = groupStack.last  // group context at first sight
            }
            if let label, !label.isEmpty { nodeLabels[token] = label }
        }

        for line in trimmedLines {
            if line.isEmpty { continue }

            // Structured / ignorable comments.
            if line.hasPrefix("%%") {
                let body = line.dropFirst(2).trimmingCharacters(in: .whitespaces)
                if body.hasPrefix("purpose ") {
                    let rest = body.dropFirst("purpose ".count)
                    if let colon = rest.firstIndex(of: ":") {
                        let token = String(rest[..<colon]).trimmingCharacters(in: .whitespaces)
                        let value = String(rest[rest.index(after: colon)...]).trimmingCharacters(in: .whitespaces)
                        if !token.isEmpty { nodePurpose[token] = value }
                    }
                } else if body.hasPrefix("hidden ") {
                    let token = String(body.dropFirst("hidden ".count)).trimmingCharacters(in: .whitespaces)
                    if !token.isEmpty { nodeHidden.insert(token) }
                } else if body.hasPrefix("group-hidden ") {
                    let token = String(body.dropFirst("group-hidden ".count)).trimmingCharacters(in: .whitespaces)
                    if !token.isEmpty { groupHidden.insert(token) }
                }
                continue  // all other comments (banner, action-lane note) are ignored
            }

            let lower = line.lowercased()
            if ignoredPrefixes.contains(where: { lower.hasPrefix($0) }) { continue }

            // The first meaningful line must be a graph header.
            if !headerSeen {
                if lower.hasPrefix("graph") || lower.hasPrefix("flowchart") {
                    headerSeen = true
                    continue
                }
                return .failure(.notAGraph)
            }

            if lower == "end" {
                if groupStack.isEmpty { return .failure(.unbalancedSubgraph) }
                groupStack.removeLast()
                continue
            }

            if lower.hasPrefix("subgraph") {
                guard let sub = OverlayComposition.parseSubgraph(line) else {
                    return .failure(.malformedNode(line))
                }
                if !seenGroup.contains(sub.token) {
                    seenGroup.insert(sub.token)
                    groupOrder.append(sub.token)
                    groupTitles[sub.token] = sub.title
                } else if !sub.title.isEmpty {
                    groupTitles[sub.token] = sub.title
                }
                groupStack.append(sub.token)
                continue
            }

            // Edge (arrow outside any label) vs node declaration.
            if OverlayComposition.hasEdgeArrow(line) {
                guard let parsed = OverlayComposition.parseEdge(line),
                      let fromNode = OverlayComposition.parseNode(parsed.from),
                      let toNode = OverlayComposition.parseNode(parsed.to) else {
                    return .failure(.malformedEdge(line))
                }
                registerNode(token: fromNode.token, label: fromNode.label)
                registerNode(token: toNode.token, label: toNode.label)
                edges.append((from: fromNode.token, label: parsed.label, to: toNode.token))
                continue
            }

            // Node declaration.
            guard let node = OverlayComposition.parseNode(line) else {
                return .failure(.malformedNode(line))
            }
            registerNode(token: node.token, label: node.label)
        }

        guard headerSeen else { return .failure(.notAGraph) }
        guard groupStack.isEmpty else { return .failure(.unbalancedSubgraph) }

        // ---- Build the merged composition -------------------------------------------

        var layersByToken: [String: OverlayLayer] = [:]
        for layer in layers { layersByToken[OverlayComposition.mermaidToken(layer.id)] = layer }
        var groupsByToken: [String: OverlayGroup] = [:]
        var groupsByNameToken: [String: OverlayGroup] = [:]
        for group in groups {
            groupsByToken[OverlayComposition.mermaidToken(group.id)] = group
            groupsByNameToken[OverlayComposition.mermaidToken(group.name)] = group
        }

        // Groups first, so nodes can resolve their group id.
        var resultGroups: [OverlayGroup] = []
        var groupIDForToken: [String: String] = [:]
        for token in groupOrder {
            let title = groupTitles[token] ?? ""
            let visible = !groupHidden.contains(token)
            let existing = groupsByToken[token] ?? groupsByNameToken[OverlayComposition.mermaidToken(title)]
            let resolved: OverlayGroup
            if let existing {
                resolved = OverlayGroup(
                    id: existing.id,
                    name: title.isEmpty ? existing.name : title,
                    visible: visible
                )
            } else {
                resolved = OverlayGroup(
                    id: OverlayGroup.newID(),
                    name: title.isEmpty ? token : title,
                    visible: visible
                )
            }
            resultGroups.append(resolved)
            groupIDForToken[token] = resolved.id
        }

        var resultLayers: [OverlayLayer] = []
        var layerIDForToken: [String: String] = [:]
        var newLaneCursor = (layers.map(\.actionLaneIndex).max() ?? -1) + 1
        for token in orderedNodeTokens {
            let explicitLabel = nodeLabels[token]
            let resolvedGroupID = (nodeGroupToken[token] ?? nil).flatMap { groupIDForToken[$0] }
            let hidden = nodeHidden.contains(token)
            if let existing = layersByToken[token] {
                var updated = existing
                if let label = explicitLabel, !label.isEmpty { updated.label = label }
                updated.groupID = resolvedGroupID
                updated.purpose = nodePurpose[token] ?? ""
                updated.visible = !hidden
                resultLayers.append(updated)
                layerIDForToken[token] = updated.id
            } else {
                let label = (explicitLabel?.isEmpty == false) ? explicitLabel! : OverlayRelationshipKind.humanize(token)
                let created = OverlayLayer(
                    label: label,
                    purpose: nodePurpose[token] ?? "",
                    normalizedRect: OverlayComposition.defaultAuthoredRect,
                    actionLaneIndex: newLaneCursor,
                    groupID: resolvedGroupID,
                    visible: !hidden
                )
                newLaneCursor += 1
                resultLayers.append(created)
                layerIDForToken[token] = created.id
            }
        }

        // Edges become exactly the parsed set. An unchanged edge keeps its id so
        // applying the same graph twice does not churn the model.
        var resultRelationships: [OverlayRelationship] = []
        var seenEdgeKey = Set<String>()
        for edge in edges {
            guard let fromID = layerIDForToken[edge.from], let toID = layerIDForToken[edge.to],
                  fromID != toID else { continue }
            let kind = OverlayRelationshipKind(rawValue: edge.label ?? OverlayRelationshipKind.related.rawValue)
            let key = "\(fromID)|\(toID)|\(kind.rawValue)"
            if seenEdgeKey.contains(key) { continue }
            seenEdgeKey.insert(key)
            let existing = relationships.first {
                $0.fromLayerID == fromID && $0.toLayerID == toID && $0.kind == kind
            }
            resultRelationships.append(
                OverlayRelationship(
                    id: existing?.id ?? OverlayRelationship.newID(),
                    fromLayerID: fromID,
                    toLayerID: toID,
                    kind: kind
                )
            )
        }

        var result = OverlayComposition(
            groups: resultGroups,
            layers: resultLayers,
            relationships: resultRelationships
        )
        result.pruneDanglingRelationships()  // belt-and-suspenders; nothing should dangle
        return .success(result)
    }

    // MARK: Line parsers

    /// Parse a `subgraph` line into (token, title). Supports `subgraph id["Title"]`,
    /// `subgraph id[Title]`, `subgraph id`, `subgraph "Title"`, and `subgraph Title`.
    fileprivate static func parseSubgraph(_ line: String) -> (token: String, title: String)? {
        var rest = String(line.dropFirst("subgraph".count)).trimmingCharacters(in: .whitespaces)
        guard !rest.isEmpty else { return (token: "subgraph_anon", title: "") }

        var idPart = rest
        var title = ""
        if let bracket = rest.firstIndex(of: "[") {
            idPart = String(rest[..<bracket]).trimmingCharacters(in: .whitespaces)
            if rest.hasSuffix("]") {
                var inner = String(rest[rest.index(after: bracket)..<rest.index(before: rest.endIndex)])
                    .trimmingCharacters(in: .whitespaces)
                inner = stripQuotes(inner)
                title = unescapeLabel(inner)
            }
        } else {
            rest = stripQuotes(rest)
            idPart = rest
            title = rest
        }
        let token = mermaidToken(idPart.isEmpty ? title : idPart)
        guard !token.isEmpty else { return nil }
        return (token, title)
    }

    /// Parse a node declaration / edge endpoint into (token, optional label). Supports
    /// `id["Label"]`, `id[Label]`, and a bare `id`.
    fileprivate static func parseNode(_ raw: String) -> (token: String, label: String?)? {
        let line = raw.trimmingCharacters(in: .whitespaces)
        if let bracket = line.firstIndex(of: "["), line.hasSuffix("]") {
            let token = String(line[..<bracket]).trimmingCharacters(in: .whitespaces)
            guard isMermaidToken(token) else { return nil }
            var inner = String(line[line.index(after: bracket)..<line.index(before: line.endIndex)])
                .trimmingCharacters(in: .whitespaces)
            inner = stripQuotes(inner)
            return (token, unescapeLabel(inner))
        }
        guard isMermaidToken(line) else { return nil }
        return (line, nil)
    }

    /// Parse an edge into (fromRaw, optional kind label, toRaw). Endpoint strings are
    /// returned raw (they may carry inline `[Label]`s) for `parseNode` to finish.
    /// Supports `a -->|label| b`, `a --> b`, `a ---|label| b`, `a --- b`, and the
    /// embedded `a -- label --> b` form.
    fileprivate static func parseEdge(_ line: String) -> (from: String, label: String?, to: String)? {
        // Embedded-label form: a -- label --> b
        if let arrowRange = line.range(of: "-->"),
           let dashRange = line.range(of: "--"),
           dashRange.lowerBound < arrowRange.lowerBound {
            let between = String(line[dashRange.upperBound..<arrowRange.lowerBound])
                .trimmingCharacters(in: .whitespaces)
            let from = String(line[..<dashRange.lowerBound]).trimmingCharacters(in: .whitespaces)
            let to = String(line[arrowRange.upperBound...]).trimmingCharacters(in: .whitespaces)
            if !between.isEmpty, !between.contains("|"), !from.isEmpty, !to.isEmpty,
               !to.hasPrefix("|") {
                return (from, between, to)
            }
        }

        for arrow in ["-->", "---"] {
            guard let arrowRange = line.range(of: arrow) else { continue }
            let from = String(line[..<arrowRange.lowerBound]).trimmingCharacters(in: .whitespaces)
            var remainder = String(line[arrowRange.upperBound...]).trimmingCharacters(in: .whitespaces)
            var label: String?
            if remainder.hasPrefix("|") {
                guard let close = remainder.dropFirst().firstIndex(of: "|") else { return nil }
                label = String(remainder[remainder.index(after: remainder.startIndex)..<close])
                    .trimmingCharacters(in: .whitespaces)
                remainder = String(remainder[remainder.index(after: close)...])
                    .trimmingCharacters(in: .whitespaces)
            }
            if from.isEmpty || remainder.isEmpty { return nil }
            return (from, (label?.isEmpty == true) ? nil : label, remainder)
        }
        return nil
    }

    private static func stripQuotes(_ s: String) -> String {
        guard s.count >= 2, s.hasPrefix("\""), s.hasSuffix("\"") else { return s }
        return String(s.dropFirst().dropLast())
    }
}
