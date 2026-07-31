import Combine
import CoreGraphics
import Foundation

// MARK: - Author-your-own overlay LAYER system (Photoshop-style)
//
// The Screen Trainer's read (the local model's candidate `ScreenRegion`s) is the
// machine's guess. This file adds the OTHER half the owner asked for: layers the
// CLINICIAN authors and stacks ON TOP of that read — imagined / annotation
// components managed Photoshop-style. Each authored overlay carries not just a
// position and a label but a PURPOSE (why this element exists in the workflow) and
// a slot in the ACTION LANE (its order in the click-sequence). Grouped by clinical
// context (e.g. inpatient / outpatient), each layer and each group shows/hides
// independently. Together these authored overlays are the seed of the semantic
// knowledge-graph of the EHR UI that the later agentic-composition layer plans
// over.
//
// PHI BOUNDARY (absolute): identical to the rest of the Screen Trainer. Nothing
// here is extracted from a real EHR screen. A layer is the clinician's OWN
// annotation — a normalized rectangle (`0…1`, never pixels, never an absolute
// screen coordinate), a label and purpose HE types, a workflow-order index, and a
// group name HE chooses. No frame, no pixels, no screen text, no patient value.
// The persisted document carries only these author-supplied, content-free fields,
// exactly as the typed correction `note` is kept on-device and never transmitted.

// MARK: - Overlay group (a clinical context)

/// A named collection of authored overlays — a clinical context such as
/// "inpatient" or "outpatient". Hiding the group hides every layer inside it,
/// Photoshop-style, without changing each layer's own visibility flag.
struct OverlayGroup: Identifiable, Equatable, Codable, Sendable {
    let id: String
    /// The clinical-context name the clinician chose, e.g. "inpatient". Content-free.
    var name: String
    /// Group-level show/hide. When false, none of its layers draw regardless of
    /// each layer's own `visible` flag.
    var visible: Bool

    init(id: String = OverlayGroup.newID(), name: String, visible: Bool = true) {
        self.id = id
        self.name = name
        self.visible = visible
    }

    static func newID() -> String { "group-\(UUID().uuidString.prefix(8))" }
}

// MARK: - Overlay layer (one authored component)

/// One overlay component the clinician authors and stacks on top of the model's
/// read. It is the atom of the EHR UI knowledge-graph: WHERE it sits
/// (`normalizedRect`), WHAT it is (`label`), WHY it exists (`purpose`), WHEN it
/// happens in the workflow (`actionLaneIndex`), and which clinical context it
/// belongs to (`groupID`). `visible` is its own Photoshop-style show/hide.
struct OverlayLayer: Identifiable, Equatable, Codable, Sendable {
    let id: String
    /// The short name the clinician gives this component, e.g. "Sign orders".
    var label: String
    /// Free text: WHY this component exists / what it accomplishes in the
    /// workflow. Author-supplied, content-free, on-device only. This is the
    /// semantic edge the future knowledge-graph carries.
    var purpose: String
    /// Position + size, normalized to the window (origin top-left, each axis
    /// `0…1`). Reuses the Screen Trainer's `NormalizedRect`, so it can never carry
    /// pixels or an absolute screen coordinate.
    var normalizedRect: NormalizedRect
    /// This component's slot in the ACTION LANE — its order in the workflow
    /// click-sequence. Lower runs earlier. The later agentic layer plans over this
    /// ordering.
    var actionLaneIndex: Int
    /// The group (clinical context) this layer belongs to, or `nil` when ungrouped.
    var groupID: String?
    /// This layer's own show/hide. Effective visibility also requires its group to
    /// be visible (see `OverlayComposition.isEffectivelyVisible`).
    var visible: Bool

    init(
        id: String = OverlayLayer.newID(),
        label: String,
        purpose: String = "",
        normalizedRect: NormalizedRect,
        actionLaneIndex: Int,
        groupID: String? = nil,
        visible: Bool = true
    ) {
        self.id = id
        self.label = label
        self.purpose = purpose
        self.normalizedRect = normalizedRect
        self.actionLaneIndex = actionLaneIndex
        self.groupID = groupID
        self.visible = visible
    }

    static func newID() -> String { "layer-\(UUID().uuidString.prefix(8))" }
}

// MARK: - Overlay composition (the whole authored document)

/// The full authored overlay document: an ordered stack of groups and the layers
/// within them. This is the persisted, PHI-free knowledge-graph seed. It is a pure
/// value type with all the Photoshop-style semantics (effective visibility,
/// render/lane ordering, add / reorder / regroup) expressed as pure functions, so
/// the whole model is unit-testable with no UI, no window, and no capture.
struct OverlayComposition: Equatable, Codable, Sendable {
    /// Groups in panel order (top of the list first).
    var groups: [OverlayGroup]
    /// Every authored layer. Panel/z order is this array order; the action-lane
    /// ordering is derived from `actionLaneIndex` independently.
    var layers: [OverlayLayer]

    init(groups: [OverlayGroup] = [], layers: [OverlayLayer] = []) {
        self.groups = groups
        self.layers = layers
    }

    /// An empty document — the default before the clinician authors anything.
    static let empty = OverlayComposition()

    // MARK: Lookups

    func group(withID id: String?) -> OverlayGroup? {
        guard let id else { return nil }
        return groups.first { $0.id == id }
    }

    func group(for layer: OverlayLayer) -> OverlayGroup? {
        group(withID: layer.groupID)
    }

    func layer(withID id: String) -> OverlayLayer? {
        layers.first { $0.id == id }
    }

    /// The layers belonging to a group (or the ungrouped layers when `groupID` is
    /// `nil`), in panel/z order.
    func layers(inGroup groupID: String?) -> [OverlayLayer] {
        layers.filter { $0.groupID == groupID }
    }

    // MARK: Effective visibility (the render guarantee)

    /// A layer draws only when it is visible AND its group (if any) is visible.
    /// A layer whose `groupID` points at a missing group is treated as ungrouped.
    func isEffectivelyVisible(_ layer: OverlayLayer) -> Bool {
        guard layer.visible else { return false }
        guard let groupID = layer.groupID else { return true }
        guard let group = groups.first(where: { $0.id == groupID }) else { return true }
        return group.visible
    }

    /// EXACTLY the layers that should be drawn, in panel/z order. Hidden layers and
    /// layers in hidden groups are excluded — this is the single source the overlay
    /// renders, so "hidden overlays don't draw" is guaranteed here, not in the view.
    var renderableLayers: [OverlayLayer] {
        layers.filter(isEffectivelyVisible)
    }

    /// The authored workflow click-sequence: every layer ordered by its action-lane
    /// slot (ties broken by panel order). This is the ordering the later agentic
    /// layer plans over.
    var actionLaneSequence: [OverlayLayer] {
        layers.enumerated()
            .sorted { lhs, rhs in
                if lhs.element.actionLaneIndex != rhs.element.actionLaneIndex {
                    return lhs.element.actionLaneIndex < rhs.element.actionLaneIndex
                }
                return lhs.offset < rhs.offset
            }
            .map(\.element)
    }

    /// The next free action-lane slot — one past the current maximum, or 0 when
    /// empty. Used to auto-assign a slot when authoring a new overlay.
    var nextActionLaneIndex: Int {
        (layers.map(\.actionLaneIndex).max() ?? -1) + 1
    }

    // MARK: Mutations (all pure — return a new composition)

    /// Author a new overlay and append it. When `actionLaneIndex` is omitted it
    /// takes the next free slot. Returns the new composition and the created layer.
    @discardableResult
    mutating func addLayer(
        label: String,
        purpose: String = "",
        normalizedRect: NormalizedRect = OverlayComposition.defaultAuthoredRect,
        actionLaneIndex: Int? = nil,
        groupID: String? = nil,
        visible: Bool = true,
        id: String = OverlayLayer.newID()
    ) -> OverlayLayer {
        let layer = OverlayLayer(
            id: id,
            label: label.trimmingCharacters(in: .whitespacesAndNewlines),
            purpose: purpose.trimmingCharacters(in: .whitespacesAndNewlines),
            normalizedRect: normalizedRect,
            actionLaneIndex: actionLaneIndex ?? nextActionLaneIndex,
            groupID: groupID,
            visible: visible
        )
        layers.append(layer)
        return layer
    }

    /// Add a new group at the top of the stack and return it.
    @discardableResult
    mutating func addGroup(name: String, visible: Bool = true, id: String = OverlayGroup.newID()) -> OverlayGroup {
        let group = OverlayGroup(
            id: id,
            name: name.trimmingCharacters(in: .whitespacesAndNewlines),
            visible: visible
        )
        groups.insert(group, at: 0)
        return group
    }

    /// Toggle one layer's own visibility.
    mutating func toggleLayer(_ id: String) {
        guard let index = layers.firstIndex(where: { $0.id == id }) else { return }
        layers[index].visible.toggle()
    }

    /// Toggle one group's visibility (hides/shows all its layers en masse).
    mutating func toggleGroup(_ id: String) {
        guard let index = groups.firstIndex(where: { $0.id == id }) else { return }
        groups[index].visible.toggle()
    }

    /// Move a layer to a different group (or ungroup it with `nil`).
    mutating func assignLayer(_ id: String, toGroup groupID: String?) {
        guard let index = layers.firstIndex(where: { $0.id == id }) else { return }
        layers[index].groupID = groupID
    }

    /// Replace an authored layer wholesale (edit label / purpose / lane / rect).
    mutating func updateLayer(_ layer: OverlayLayer) {
        guard let index = layers.firstIndex(where: { $0.id == layer.id }) else { return }
        layers[index] = layer
    }

    /// Remove a layer.
    mutating func removeLayer(_ id: String) {
        layers.removeAll { $0.id == id }
    }

    /// Remove a group; its layers become ungrouped (never silently deleted).
    mutating func removeGroup(_ id: String) {
        groups.removeAll { $0.id == id }
        for index in layers.indices where layers[index].groupID == id {
            layers[index].groupID = nil
        }
    }

    /// Reorder a layer within its group siblings (Photoshop up/down in the stack).
    /// `delta` is -1 to move up, +1 to move down; clamped to the sibling range.
    mutating func moveLayer(_ id: String, by delta: Int) {
        guard let layer = layer(withID: id) else { return }
        let siblingIDs = layers(inGroup: layer.groupID).map(\.id)
        guard let localIndex = siblingIDs.firstIndex(of: id) else { return }
        let target = localIndex + delta
        guard target >= 0, target < siblingIDs.count, target != localIndex else { return }
        // Swap the two siblings' absolute positions in the flat `layers` array.
        guard let a = layers.firstIndex(where: { $0.id == siblingIDs[localIndex] }),
              let b = layers.firstIndex(where: { $0.id == siblingIDs[target] }) else { return }
        layers.swapAt(a, b)
    }

    /// Reorder a group within the group stack. `delta` -1 up / +1 down.
    mutating func moveGroup(_ id: String, by delta: Int) {
        guard let index = groups.firstIndex(where: { $0.id == id }) else { return }
        let target = index + delta
        guard target >= 0, target < groups.count, target != index else { return }
        groups.swapAt(index, target)
    }

    /// A sensible default rectangle for a freshly authored overlay: a centered box
    /// the clinician then drags into place.
    static let defaultAuthoredRect = NormalizedRect(x: 0.35, y: 0.42, width: 0.3, height: 0.16)

    // MARK: Starter document (demo + first-run illustration)

    /// A small, generic, content-free starter so the panel and the drawn overlay
    /// illustrate the concept out of the box: two clinical-context groups with a
    /// couple of authored components each, laid out along the action lane. Purely
    /// generic workflow annotations — no real screen, no PHI.
    static var starter: OverlayComposition {
        let inpatient = OverlayGroup(id: "group-inpatient", name: "inpatient", visible: true)
        let outpatient = OverlayGroup(id: "group-outpatient", name: "outpatient", visible: true)
        return OverlayComposition(
            groups: [inpatient, outpatient],
            layers: [
                OverlayLayer(
                    id: "layer-open-orders",
                    label: "Open orders tab",
                    purpose: "Start the order-entry workflow from the chart toolbar.",
                    normalizedRect: NormalizedRect(x: 0.02, y: 0.0, width: 0.16, height: 0.053),
                    actionLaneIndex: 0,
                    groupID: inpatient.id
                ),
                OverlayLayer(
                    id: "layer-order-set",
                    label: "Admission order set",
                    purpose: "Apply the standard inpatient admission bundle.",
                    normalizedRect: NormalizedRect(x: 0.05, y: 0.16, width: 0.5, height: 0.2),
                    actionLaneIndex: 1,
                    groupID: inpatient.id
                ),
                OverlayLayer(
                    id: "layer-sign",
                    label: "Sign & hold",
                    purpose: "Sign the orders; a propose-confirm gate stops here before execution.",
                    normalizedRect: NormalizedRect(x: 0.78, y: 0.905, width: 0.2, height: 0.06),
                    actionLaneIndex: 2,
                    groupID: inpatient.id
                ),
                OverlayLayer(
                    id: "layer-visit-dx",
                    label: "Visit diagnosis",
                    purpose: "Attach the outpatient visit diagnosis before checkout.",
                    normalizedRect: NormalizedRect(x: 0.29, y: 0.1, width: 0.4, height: 0.14),
                    actionLaneIndex: 0,
                    groupID: outpatient.id
                ),
            ]
        )
    }
}

// MARK: - Persistence (single PHI-free JSON document, on-device)

/// Atomic single-document JSON persistence for the authored overlay composition.
/// It sits beside the correction store under Application Support, is git-ignored,
/// and holds only author-supplied, content-free fields — labels, purposes,
/// normalized positions, workflow-order indices, group names, and visibility. No
/// frame, no pixels, no screen text; never PHI.
final class OverlayCompositionStore {
    private let fileURL: URL

    init(fileURL: URL) {
        self.fileURL = fileURL
    }

    /// The default on-device store path (git-ignored, never transmitted), grouped
    /// with the Screen Trainer's other on-device memory.
    static func defaultStore(source: String = "citrix-ehr") -> OverlayCompositionStore {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        let safe = source.map { $0.isLetter || $0.isNumber || $0 == "-" || $0 == "_" ? $0 : "-" }
        let dir = base
            .appendingPathComponent("OperationsFloater", isDirectory: true)
            .appendingPathComponent("screen-trainer-layers", isDirectory: true)
        return OverlayCompositionStore(
            fileURL: dir.appendingPathComponent("\(String(safe)).json")
        )
    }

    /// Load the saved composition, or `nil` when none exists / it is unreadable.
    func load() -> OverlayComposition? {
        guard let data = try? Data(contentsOf: fileURL) else { return nil }
        return try? JSONDecoder().decode(OverlayComposition.self, from: data)
    }

    /// Persist the composition atomically, creating the (0700) directory as needed.
    func save(_ composition: OverlayComposition) throws {
        try FileManager.default.createDirectory(
            at: fileURL.deletingLastPathComponent(),
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes, .prettyPrinted]
        let data = try encoder.encode(composition)
        try data.write(to: fileURL, options: [.atomic])
    }
}

// MARK: - Layer session (observable authored state for the panel + overlay)

/// Drives the Layers panel and feeds the drawn overlay. It owns the authored
/// `OverlayComposition`, applies every Photoshop-style mutation through the pure
/// model, and persists each change to the on-device store. The selected authored
/// layer is tracked so the panel and the drawn box stay in sync. No capture, no
/// network, and no PHI live here.
@MainActor
final class OverlayCompositionSession: ObservableObject {
    @Published private(set) var composition: OverlayComposition
    /// The authored layer currently selected in the panel (for edit / highlight).
    @Published var selectedLayerID: String?

    private let store: OverlayCompositionStore?

    init(
        composition: OverlayComposition = .empty,
        store: OverlayCompositionStore? = nil
    ) {
        // A saved document wins over the seed; otherwise use the provided initial
        // composition (the app seeds `.starter`, tests pass their own).
        self.composition = store?.load() ?? composition
        self.store = store
    }

    var selectedLayer: OverlayLayer? {
        guard let id = selectedLayerID else { return nil }
        return composition.layer(withID: id)
    }

    /// The layers that should draw (visible, in a visible group), in panel order.
    var renderableLayers: [OverlayLayer] { composition.renderableLayers }

    // MARK: Authoring

    /// Author a new overlay with a label, purpose, action-lane slot, and group,
    /// select it, and persist. This is the panel's "add overlay" affordance.
    @discardableResult
    func addOverlay(
        label: String,
        purpose: String,
        actionLaneIndex: Int? = nil,
        groupID: String? = nil,
        normalizedRect: NormalizedRect = OverlayComposition.defaultAuthoredRect
    ) -> OverlayLayer? {
        let trimmed = label.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        let layer = composition.addLayer(
            label: trimmed,
            purpose: purpose,
            normalizedRect: normalizedRect,
            actionLaneIndex: actionLaneIndex,
            groupID: groupID
        )
        selectedLayerID = layer.id
        persist()
        return layer
    }

    @discardableResult
    func addGroup(name: String) -> OverlayGroup? {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        let group = composition.addGroup(name: trimmed)
        persist()
        return group
    }

    // MARK: Visibility

    func toggleLayer(_ id: String) { mutate { $0.toggleLayer(id) } }
    func toggleGroup(_ id: String) { mutate { $0.toggleGroup(id) } }

    // MARK: Reorder / regroup / edit / delete

    func moveLayer(_ id: String, by delta: Int) { mutate { $0.moveLayer(id, by: delta) } }
    func moveGroup(_ id: String, by delta: Int) { mutate { $0.moveGroup(id, by: delta) } }
    func assignLayer(_ id: String, toGroup groupID: String?) {
        mutate { $0.assignLayer(id, toGroup: groupID) }
    }
    func updateLayer(_ layer: OverlayLayer) { mutate { $0.updateLayer(layer) } }

    func removeLayer(_ id: String) {
        mutate { $0.removeLayer(id) }
        if selectedLayerID == id { selectedLayerID = nil }
    }
    func removeGroup(_ id: String) { mutate { $0.removeGroup(id) } }

    func select(_ id: String?) { selectedLayerID = id }

    private func mutate(_ transform: (inout OverlayComposition) -> Void) {
        transform(&composition)
        persist()
    }

    private func persist() {
        try? store?.save(composition)
    }
}
