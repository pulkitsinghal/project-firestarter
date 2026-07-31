import AppKit
import Combine
import CoreGraphics
import Foundation
import SwiftUI

// MARK: - Authored-overlay accents

extension OverlayComposition {
    /// A stable, generic accent palette indexed by group order — so each clinical
    /// context reads as its own color in both the panel and the drawn overlay.
    static let groupPalette: [Color] = [.blue, .orange, .purple, .teal, .pink, .indigo, .green]

    /// The accent for a layer: its group's palette color, or gray when ungrouped.
    func accent(for layer: OverlayLayer) -> Color {
        guard let groupID = layer.groupID,
              let index = groups.firstIndex(where: { $0.id == groupID }) else {
            return .gray
        }
        return Self.groupPalette[index % Self.groupPalette.count]
    }

    func accent(forGroup group: OverlayGroup) -> Color {
        guard let index = groups.firstIndex(where: { $0.id == group.id }) else { return .gray }
        return Self.groupPalette[index % Self.groupPalette.count]
    }
}

// MARK: - Authored overlays render layer (reuses the box-drawing plumbing)

/// Draws the CLINICIAN-authored overlays over the target area — the counterpart to
/// `ScreenTrainerRegionsLayer` (which draws the model's read). It renders EXACTLY
/// `composition.renderableLayers`, so hidden layers and layers in hidden groups
/// never draw. Each box is solid (authored, not a guess), carries the label and its
/// action-lane slot, and reuses the same `NormalizedRect.cgRect(in:)` mapping as
/// the model-read layer.
struct AuthoredOverlaysLayer: View {
    let composition: OverlayComposition
    var selectedLayerID: String?

    var body: some View {
        GeometryReader { geometry in
            let size = geometry.size
            ZStack(alignment: .topLeading) {
                ForEach(composition.renderableLayers) { layer in
                    layerBox(layer, in: size)
                }
            }
            .frame(width: size.width, height: size.height)
        }
    }

    @ViewBuilder
    private func layerBox(_ layer: OverlayLayer, in size: CGSize) -> some View {
        let rect = layer.normalizedRect.cgRect(in: size)
        let isSelected = layer.id == selectedLayerID
        let accent = composition.accent(for: layer)

        ZStack(alignment: .topLeading) {
            RoundedRectangle(cornerRadius: 4)
                .strokeBorder(accent, lineWidth: isSelected ? 3 : 2)
                .background(
                    RoundedRectangle(cornerRadius: 4)
                        .fill(accent.opacity(isSelected ? 0.20 : 0.12))
                )
                .frame(width: rect.width, height: rect.height)

            layerTag(layer, accent: accent).offset(y: -1)
        }
        .frame(width: rect.width, height: rect.height, alignment: .topLeading)
        .offset(x: rect.minX, y: rect.minY)
    }

    private func layerTag(_ layer: OverlayLayer, accent: Color) -> some View {
        HStack(spacing: 4) {
            Text("\(layer.actionLaneIndex)")
                .font(.system(size: 8, weight: .bold).monospacedDigit())
                .foregroundStyle(accent)
                .padding(.horizontal, 3)
                .padding(.vertical, 1)
                .background(.white, in: RoundedRectangle(cornerRadius: 2))
            Text(layer.label)
                .font(.system(size: 9, weight: .bold))
        }
        .foregroundStyle(.white)
        .padding(.horizontal, 5)
        .padding(.vertical, 2)
        .background(accent, in: RoundedRectangle(cornerRadius: 3))
        .fixedSize()
    }
}

// MARK: - Layers panel (Photoshop-style)

/// The Photoshop-style Layers panel: every group and its authored layers, each
/// with a show/hide eye and reorder controls, plus an "add overlay" affordance that
/// authors a component with a label, a PURPOSE, an action-lane slot, and a group.
/// The live overlay uses the interactive form; the headless demo renders a
/// read-only list (SwiftUI text fields do not rasterize offscreen).
struct ScreenTrainerLayersPanel: View {
    @ObservedObject var session: OverlayCompositionSession
    var interactive: Bool = true

    @State private var draftLabel = ""
    @State private var draftPurpose = ""
    @State private var draftLaneText = ""
    @State private var draftGroupID: String?
    @State private var draftGroupName = ""
    @State private var showAddForm = false

    private var composition: OverlayComposition { session.composition }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            header
            if composition.groups.isEmpty && composition.layers.isEmpty {
                emptyState
            } else {
                stack
            }
            if interactive {
                addControls
            }
            phiFootnote
        }
        .foregroundStyle(.white)
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(.black.opacity(0.80))
    }

    private var header: some View {
        HStack(spacing: 6) {
            Image(systemName: "square.stack.3d.up.fill").font(.system(size: 10))
            Text("LAYERS")
                .font(.system(size: 9, weight: .bold))
            Spacer()
            Text("\(composition.renderableLayers.count)/\(composition.layers.count) shown")
                .font(.system(size: 9).monospacedDigit())
                .foregroundStyle(.white.opacity(0.6))
        }
    }

    private var emptyState: some View {
        Text("No overlays yet. Add a group (a clinical context) and author an overlay "
            + "with a label, a purpose, and an action-lane slot.")
            .font(.system(size: 10))
            .foregroundStyle(.white.opacity(0.55))
            .fixedSize(horizontal: false, vertical: true)
    }

    // MARK: Stack (groups + their layers, then ungrouped)

    private var stack: some View {
        VStack(alignment: .leading, spacing: 4) {
            ForEach(composition.groups) { group in
                groupRow(group)
                ForEach(composition.layers(inGroup: group.id)) { layer in
                    layerRow(layer, groupVisible: group.visible)
                        .padding(.leading, 16)
                }
            }
            let ungrouped = composition.layers(inGroup: nil)
            if !ungrouped.isEmpty {
                Text("UNGROUPED")
                    .font(.system(size: 8, weight: .bold))
                    .foregroundStyle(.white.opacity(0.4))
                    .padding(.top, 2)
                ForEach(ungrouped) { layer in
                    layerRow(layer, groupVisible: true)
                }
            }
        }
    }

    private func groupRow(_ group: OverlayGroup) -> some View {
        HStack(spacing: 6) {
            eyeButton(isOn: group.visible) { session.toggleGroup(group.id) }
            Circle().fill(composition.accent(forGroup: group)).frame(width: 8, height: 8)
            Text(group.name)
                .font(.system(size: 10, weight: .bold))
                .foregroundStyle(group.visible ? .white : .white.opacity(0.4))
            Text("(\(composition.layers(inGroup: group.id).count))")
                .font(.system(size: 9).monospacedDigit())
                .foregroundStyle(.white.opacity(0.4))
            Spacer()
            if interactive {
                reorderButtons(
                    up: { session.moveGroup(group.id, by: -1) },
                    down: { session.moveGroup(group.id, by: 1) }
                )
            }
        }
        .padding(.vertical, 2)
        .padding(.horizontal, 4)
        .background(.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 4))
    }

    private func layerRow(_ layer: OverlayLayer, groupVisible: Bool) -> some View {
        let effective = session.composition.isEffectivelyVisible(layer)
        let isSelected = layer.id == session.selectedLayerID
        return HStack(alignment: .top, spacing: 6) {
            eyeButton(isOn: layer.visible) { session.toggleLayer(layer.id) }
            laneBadge(layer.actionLaneIndex, accent: composition.accent(for: layer))
            VStack(alignment: .leading, spacing: 1) {
                Text(layer.label)
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(effective ? .white : .white.opacity(0.4))
                if !layer.purpose.isEmpty {
                    Text(layer.purpose)
                        .font(.system(size: 9))
                        .foregroundStyle(.white.opacity(effective ? 0.7 : 0.35))
                        .lineLimit(2)
                }
                if layer.visible && !groupVisible {
                    Text("hidden by group")
                        .font(.system(size: 8, weight: .medium))
                        .foregroundStyle(.orange.opacity(0.8))
                }
            }
            Spacer(minLength: 4)
            if interactive {
                reorderButtons(
                    up: { session.moveLayer(layer.id, by: -1) },
                    down: { session.moveLayer(layer.id, by: 1) }
                )
            }
        }
        .padding(.vertical, 3)
        .padding(.horizontal, 5)
        .background(
            (isSelected ? Color.white.opacity(0.14) : Color.clear),
            in: RoundedRectangle(cornerRadius: 4)
        )
        .contentShape(Rectangle())
        .onTapGesture { session.select(isSelected ? nil : layer.id) }
    }

    private func laneBadge(_ index: Int, accent: Color) -> some View {
        Text("\(index)")
            .font(.system(size: 9, weight: .bold).monospacedDigit())
            .foregroundStyle(.white)
            .frame(width: 16, height: 16)
            .background(accent, in: RoundedRectangle(cornerRadius: 3))
    }

    private func eyeButton(isOn: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: isOn ? "eye.fill" : "eye.slash")
                .font(.system(size: 10))
                .foregroundStyle(isOn ? .white : .white.opacity(0.35))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(isOn ? "Hide" : "Show")
    }

    private func reorderButtons(
        up: @escaping () -> Void,
        down: @escaping () -> Void
    ) -> some View {
        HStack(spacing: 2) {
            Button(action: up) { Image(systemName: "chevron.up") }
                .buttonStyle(.plain).font(.system(size: 8)).foregroundStyle(.white.opacity(0.6))
            Button(action: down) { Image(systemName: "chevron.down") }
                .buttonStyle(.plain).font(.system(size: 8)).foregroundStyle(.white.opacity(0.6))
        }
    }

    // MARK: Add controls (author your own overlay)

    @ViewBuilder
    private var addControls: some View {
        Divider().overlay(Color.white.opacity(0.15))
        HStack(spacing: 6) {
            TextField("New group (e.g. inpatient)", text: $draftGroupName)
                .textFieldStyle(.roundedBorder)
                .font(.system(size: 10))
                .onSubmit(addGroup)
            Button("Add group", action: addGroup)
                .controlSize(.mini)
                .disabled(draftGroupName.trimmingCharacters(in: .whitespaces).isEmpty)
            Button(showAddForm ? "Cancel" : "Add overlay") {
                showAddForm.toggle()
            }
            .controlSize(.mini)
        }
        if showAddForm {
            addOverlayForm
        }
    }

    private var addOverlayForm: some View {
        VStack(alignment: .leading, spacing: 5) {
            TextField("Label (e.g. Sign orders)", text: $draftLabel)
                .textFieldStyle(.roundedBorder).font(.system(size: 10))
            TextField("Purpose — why this step exists", text: $draftPurpose)
                .textFieldStyle(.roundedBorder).font(.system(size: 10))
            HStack(spacing: 6) {
                Text("Action-lane slot")
                    .font(.system(size: 9)).foregroundStyle(.white.opacity(0.7))
                TextField("\(composition.nextActionLaneIndex)", text: $draftLaneText)
                    .textFieldStyle(.roundedBorder).font(.system(size: 10).monospacedDigit())
                    .frame(width: 46)
                Picker("Group", selection: $draftGroupID) {
                    Text("Ungrouped").tag(String?.none)
                    ForEach(composition.groups) { group in
                        Text(group.name).tag(String?.some(group.id))
                    }
                }
                .controlSize(.mini)
                .font(.system(size: 9))
                Spacer()
                Button("Author") { addOverlay() }
                    .controlSize(.small)
                    .disabled(draftLabel.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .padding(7)
        .background(.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 6))
    }

    private var phiFootnote: some View {
        HStack(spacing: 5) {
            Image(systemName: "checkmark.shield.fill").font(.system(size: 9))
            Text("Layers store only your labels, purposes, positions & order — on-device, never PHI.")
                .font(.system(size: 9))
        }
        .foregroundStyle(.green.opacity(0.7))
    }

    // MARK: Actions

    private func addGroup() {
        _ = session.addGroup(name: draftGroupName)
        draftGroupName = ""
    }

    private func addOverlay() {
        let lane = Int(draftLaneText.trimmingCharacters(in: .whitespaces))
        _ = session.addOverlay(
            label: draftLabel,
            purpose: draftPurpose,
            actionLaneIndex: lane,
            groupID: draftGroupID
        )
        draftLabel = ""
        draftPurpose = ""
        draftLaneText = ""
        showAddForm = false
    }
}

// MARK: - "What I've learned" panel (statements + editable mermaid)

/// The knowledge-graph view the owner asked for: what the trainer has learned about
/// the EHR UI, shown BOTH as plain statements ("Open orders tab navigates to Admission
/// order set") AND as an editable mermaid graph he can visualize and hand-edit. Apply
/// commits the edited mermaid back into the semantic model; a bad edit is rejected with
/// a message and never corrupts the graph. Reuses the Layers panel's styling. The live
/// overlay uses the editable `TextEditor`; the headless demo renders the mermaid as
/// static text (SwiftUI editors do not rasterize offscreen).
struct LearnedGraphPanel: View {
    @ObservedObject var session: OverlayCompositionSession
    var interactive: Bool = true

    private var composition: OverlayComposition { session.composition }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            header
            statements
            Divider().overlay(Color.white.opacity(0.15))
            mermaidSection
            phiFootnote
        }
        .foregroundStyle(.white)
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(.black.opacity(0.80))
    }

    private var header: some View {
        HStack(spacing: 6) {
            Image(systemName: "brain.head.profile").font(.system(size: 10))
            Text("WHAT I'VE LEARNED")
                .font(.system(size: 9, weight: .bold))
            Spacer()
            Text("\(composition.layers.count) nodes · \(composition.relationships.count) links")
                .font(.system(size: 9).monospacedDigit())
                .foregroundStyle(.white.opacity(0.6))
        }
    }

    @ViewBuilder
    private var statements: some View {
        let lines = session.learnedStatements
        if lines.isEmpty {
            Text("Nothing yet. Author overlays and link them (e.g. a tab houses a button) "
                + "to build the graph.")
                .font(.system(size: 10))
                .foregroundStyle(.white.opacity(0.55))
                .fixedSize(horizontal: false, vertical: true)
        } else {
            VStack(alignment: .leading, spacing: 2) {
                ForEach(Array(lines.enumerated()), id: \.offset) { _, line in
                    HStack(alignment: .top, spacing: 5) {
                        Text("•").foregroundStyle(.white.opacity(0.5))
                        Text(line)
                            .font(.system(size: 10))
                            .foregroundStyle(.white.opacity(0.85))
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private var mermaidSection: some View {
        HStack(spacing: 6) {
            Image(systemName: "point.3.connected.trianglepath.dotted").font(.system(size: 10))
            Text("MERMAID — edit the graph, then Apply")
                .font(.system(size: 9, weight: .bold))
            Spacer()
        }
        .foregroundStyle(.white.opacity(0.85))

        if interactive {
            TextEditor(text: $session.mermaidDraft)
                .font(.system(size: 10, design: .monospaced))
                .scrollContentBackground(.hidden)
                .frame(minHeight: 120, maxHeight: 220)
                .padding(6)
                .background(.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 6))
            HStack(spacing: 8) {
                Button("Apply edits") { session.applyMermaid() }
                    .controlSize(.small)
                Button("Refresh from graph") { session.refreshMermaidFromModel() }
                    .controlSize(.small)
                Spacer()
            }
            if let error = session.mermaidError {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(.system(size: 9))
                    .foregroundStyle(.orange)
                    .fixedSize(horizontal: false, vertical: true)
            }
        } else {
            Text(session.mermaidDraft)
                .font(.system(size: 9, design: .monospaced))
                .foregroundStyle(.white.opacity(0.8))
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(6)
                .background(.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 6))
        }
    }

    private var phiFootnote: some View {
        HStack(spacing: 5) {
            Image(systemName: "checkmark.shield.fill").font(.system(size: 9))
            Text("The graph stores only your labels, purposes & relationship types — "
                + "on-device, never PHI.")
                .font(.system(size: 9))
        }
        .foregroundStyle(.green.opacity(0.7))
    }
}
