import Foundation
import SwiftUI

enum QueueRaceSort: String, CaseIterable, Identifiable, Sendable {
    case sourceOrder
    case recentlyActive
    case finishFirst
    case memory
    case cpu
    case needsAttention

    var id: Self { self }

    var label: String {
        switch self {
        case .sourceOrder:
            "Queue order"
        case .recentlyActive:
            "Last active"
        case .finishFirst:
            "Closest to finish"
        case .memory:
            "Most memory"
        case .cpu:
            "Most CPU"
        case .needsAttention:
            "Needs attention"
        }
    }

    var systemImage: String {
        switch self {
        case .sourceOrder:
            "list.number"
        case .recentlyActive:
            "clock.arrow.circlepath"
        case .finishFirst:
            "flag.checkered"
        case .memory:
            "memorychip"
        case .cpu:
            "cpu"
        case .needsAttention:
            "exclamationmark.triangle"
        }
    }
}

enum QueueRaceSorter {
    static func sorted(
        _ records: [QueueRecord],
        by sort: QueueRaceSort
    ) -> [QueueRecord] {
        guard sort != .sourceOrder else { return records }
        let indexed = Array(records.enumerated())
        return indexed.sorted { left, right in
            let comparison: ComparisonResult
            switch sort {
            case .sourceOrder:
                comparison = .orderedSame
            case .recentlyActive:
                comparison = compareAscending(
                    left.element.lastActiveSeconds,
                    right.element.lastActiveSeconds
                )
            case .finishFirst:
                comparison = compareDescending(
                    left.element.progressFraction,
                    right.element.progressFraction
                )
            case .memory:
                comparison = compareDescending(left.element.memoryMB, right.element.memoryMB)
            case .cpu:
                comparison = compareDescending(left.element.cpuPercent, right.element.cpuPercent)
            case .needsAttention:
                comparison = compareDescending(
                    attentionScore(left.element),
                    attentionScore(right.element)
                )
            }
            return comparison == .orderedSame
                ? left.offset < right.offset
                : comparison == .orderedAscending
        }.map(\.element)
    }

    private static func compareAscending<T: Comparable>(
        _ left: T?,
        _ right: T?
    ) -> ComparisonResult {
        switch (left, right) {
        case let (.some(left), .some(right)):
            if left < right { return .orderedAscending }
            if left > right { return .orderedDescending }
            return .orderedSame
        case (.some, .none):
            return .orderedAscending
        case (.none, .some):
            return .orderedDescending
        case (.none, .none):
            return .orderedSame
        }
    }

    private static func compareDescending<T: Comparable>(
        _ left: T?,
        _ right: T?
    ) -> ComparisonResult {
        switch (left, right) {
        case let (.some(left), .some(right)):
            if left > right { return .orderedAscending }
            if left < right { return .orderedDescending }
            return .orderedSame
        case (.some, .none):
            return .orderedAscending
        case (.none, .some):
            return .orderedDescending
        case (.none, .none):
            return .orderedSame
        }
    }

    private static func attentionScore(_ record: QueueRecord) -> Int {
        let stateScore =
            switch record.state {
            case .waiting: 50
            case .running: 30
            case .queued: 20
            case .ready: 0
            }
        let verificationScore =
            switch record.verification {
            case .unavailable, .notImplemented: 30
            case .estimated: 10
            case .verified: 0
            }
        let staleScore =
            switch record.lastActiveSeconds {
            case .some(let seconds) where seconds >= 86_400: 20
            case .some(let seconds) where seconds >= 3_600: 10
            default: 0
            }
        return stateScore + verificationScore + staleScore
    }
}

struct QueueRaceBoard: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    let records: [QueueRecord]
    let metrics: DashboardLayoutMetrics
    @Binding var isCollapsed: Bool

    @State private var sort: QueueRaceSort = .recentlyActive
    @State private var expandedRecordID: String?
    @State private var hoveredRecordID: String?

    init(
        records: [QueueRecord],
        metrics: DashboardLayoutMetrics,
        isCollapsed: Binding<Bool> = .constant(false)
    ) {
        self.records = records
        self.metrics = metrics
        _isCollapsed = isCollapsed
    }

    private var sortedRecords: [QueueRecord] {
        QueueRaceSorter.sorted(records, by: sort)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .center, spacing: 8) {
                VStack(alignment: .leading, spacing: 1) {
                    Text("WORK RACES")
                        .font(.caption2.weight(.bold))
                        .foregroundStyle(.secondary)
                    Text("\(records.count) lanes · sorted by \(sort.label.lowercased())")
                        .font(.system(size: 9))
                        .foregroundStyle(.tertiary)
                }
                Spacer(minLength: 8)
                if !isCollapsed {
                    Picker("Sort work races", selection: $sort) {
                        ForEach(QueueRaceSort.allCases) { option in
                            Label(option.label, systemImage: option.systemImage)
                                .tag(option)
                        }
                    }
                    .pickerStyle(.menu)
                    .controlSize(.small)
                    .labelsHidden()
                    .accessibilityLabel("Sort work races")
                }
                Button {
                    isCollapsed.toggle()
                } label: {
                    Image(
                        systemName: isCollapsed
                            ? "chevron.right"
                            : "chevron.down"
                    )
                }
                .buttonStyle(.plain)
                .accessibilityLabel(
                    "\(isCollapsed ? "Expand" : "Collapse") Work Races"
                )
            }
            .padding(.horizontal, metrics.recordPadding)
            .padding(.vertical, 7)

            if !isCollapsed {
                Divider()

                if sortedRecords.isEmpty {
                    ContentUnavailableView(
                        "No active work lanes",
                        systemImage: "flag.checkered",
                        description: Text("No verified running, queued, waiting, or ready work was supplied.")
                    )
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 18)
                } else {
                    HStack {
                        Text("0% · START")
                        Spacer()
                        Text("Steps added can move a task backward")
                        Spacer()
                        Text("FINISH · 100%")
                    }
                    .font(.system(size: 8, weight: .semibold))
                    .foregroundStyle(.tertiary)
                    .padding(.horizontal, metrics.recordPadding)
                    .padding(.vertical, 6)

                    VStack(spacing: 0) {
                        ForEach(Array(sortedRecords.enumerated()), id: \.element.id) { rank, record in
                            QueueRaceLane(
                                record: record,
                                rank: rank + 1,
                                metrics: metrics,
                                isExpanded: expandedRecordID == record.id,
                                isHovered: hoveredRecordID == record.id,
                                onToggleExpanded: {
                                    withAnimation(reduceMotion ? nil : .snappy(duration: 0.24)) {
                                        expandedRecordID =
                                            expandedRecordID == record.id ? nil : record.id
                                    }
                                },
                                onHover: { hovering in
                                    withAnimation(reduceMotion ? nil : .easeOut(duration: 0.16)) {
                                        hoveredRecordID = hovering ? record.id : nil
                                    }
                                }
                            )
                        }
                    }
                    .animation(
                        reduceMotion ? nil : .spring(response: 0.5, dampingFraction: 0.86),
                        value: sortedRecords.map(\.id)
                    )
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .background(.quaternary, in: RoundedRectangle(cornerRadius: 11))
        .clipShape(RoundedRectangle(cornerRadius: 11))
    }
}

private struct QueueRaceLane: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    let record: QueueRecord
    let rank: Int
    let metrics: DashboardLayoutMetrics
    let isExpanded: Bool
    let isHovered: Bool
    let onToggleExpanded: () -> Void
    let onHover: (Bool) -> Void

    private var progress: Double {
        record.progressFraction ?? 0
    }

    private var accent: Color {
        switch record.state {
        case .running:
            .cyan
        case .queued:
            .orange
        case .waiting:
            .purple
        case .ready:
            .green
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(alignment: .firstTextBaseline, spacing: 7) {
                Text(String(format: "%02d", rank))
                    .font(.system(size: 9, weight: .bold, design: .monospaced))
                    .foregroundStyle(.tertiary)
                    .frame(width: 19, alignment: .leading)
                Text(record.title)
                    .font(.caption.weight(.semibold))
                    .lineLimit(1)
                stateBadge
                Spacer(minLength: 4)
                Text(progressLabel)
                    .font(.caption2.monospacedDigit().weight(.bold))
                    .foregroundStyle(accent)
            }

            raceRail

            HStack(spacing: 8) {
                Label(activityLabel, systemImage: "clock")
                Label(memoryLabel, systemImage: "memorychip")
                Label(cpuLabel, systemImage: "cpu")
                Spacer(minLength: 0)
                Button(isExpanded ? "Less" : "Details") {
                    onToggleExpanded()
                }
                .buttonStyle(.plain)
                .font(.system(size: 9, weight: .semibold))
            }
            .font(.system(size: 9))
            .foregroundStyle(.secondary)

            if isHovered || isExpanded {
                detailPanel
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .padding(metrics.recordPadding)
        .contentShape(Rectangle())
        .onHover(perform: onHover)
        .help(hoverSummary)
        .overlay(alignment: .bottom) {
            Divider()
        }
        .zIndex(isHovered || isExpanded ? 1 : 0)
        .accessibilityElement(children: .contain)
        .accessibilityLabel(
            "\(record.title), \(record.state.rawValue), \(progressLabel), "
                + "\(activityLabel), \(memoryLabel), \(cpuLabel)"
        )
    }

    private var raceRail: some View {
        GeometryReader { geometry in
            let chipWidth = min(126, max(76, geometry.size.width * 0.22))
            let travel = max(0, geometry.size.width - chipWidth)
            let chipOffset = travel * progress
            ZStack(alignment: .leading) {
                Capsule()
                    .fill(Color.secondary.opacity(0.14))
                    .frame(height: 8)
                    .overlay(alignment: .leading) {
                        Capsule()
                            .fill(accent.opacity(0.4))
                            .frame(width: chipOffset + chipWidth / 2, height: 8)
                    }
                    .overlay {
                        HStack {
                            ForEach(0..<5, id: \.self) { index in
                                Rectangle()
                                    .fill(Color.primary.opacity(index == 0 || index == 4 ? 0.28 : 0.16))
                                    .frame(width: 1, height: index == 0 || index == 4 ? 12 : 8)
                                if index < 4 { Spacer() }
                            }
                        }
                    }
                    .padding(.vertical, 11)

                Button {
                    onToggleExpanded()
                } label: {
                    HStack(spacing: 4) {
                        Image(systemName: stateIcon)
                        Text(chipLabel)
                            .lineLimit(1)
                    }
                    .font(.system(size: 9, weight: .bold))
                    .foregroundStyle(.white)
                    .frame(width: chipWidth, height: 26)
                    .background(
                        RoundedRectangle(cornerRadius: 7)
                            .fill(accent.gradient)
                            .shadow(color: accent.opacity(0.32), radius: 4, y: 2)
                    )
                }
                .buttonStyle(.plain)
                .offset(x: chipOffset)
                .accessibilityLabel("Open \(record.title) details")
            }
            .animation(
                reduceMotion ? nil : .spring(response: 0.62, dampingFraction: 0.78),
                value: progress
            )
            .animation(
                reduceMotion ? nil : .easeInOut(duration: 0.25),
                value: record.state
            )
        }
        .frame(height: 30)
    }

    private var detailPanel: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(record.detail)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            if let currentStep = record.currentStep {
                HStack(alignment: .firstTextBaseline, spacing: 5) {
                    Text("NOW")
                        .font(.system(size: 8, weight: .bold))
                        .foregroundStyle(accent)
                    Text(currentStep)
                        .font(.caption2.weight(.medium))
                }
            }
            LazyVGrid(
                columns: Array(
                    repeating: GridItem(.flexible(minimum: 76), alignment: .leading),
                    count: metrics.density == .dense ? 3 : 2
                ),
                alignment: .leading,
                spacing: 5
            ) {
                detailMetric("Steps", stepsLabel)
                detailMetric("Progress", progressLabel)
                detailMetric("Last active", activityLabel)
                detailMetric("Memory", memoryLabel)
                detailMetric("CPU", cpuLabel)
                detailMetric("Evidence", record.verification.rawValue)
            }
        }
        .padding(8)
        .background(accent.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
    }

    private func detailMetric(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(label.uppercased())
                .font(.system(size: 7, weight: .bold))
                .foregroundStyle(.tertiary)
            Text(value.replacingOccurrences(of: "-", with: " "))
                .font(.system(size: 9, weight: .medium))
                .lineLimit(1)
        }
    }

    private var stateBadge: some View {
        Text(record.state.rawValue.uppercased())
            .font(.system(size: 8, weight: .bold))
            .foregroundStyle(accent)
            .padding(.horizontal, 5)
            .padding(.vertical, 2)
            .background(accent.opacity(0.12), in: Capsule())
    }

    private var stateIcon: String {
        switch record.state {
        case .running:
            "play.fill"
        case .queued:
            "hourglass"
        case .waiting:
            "pause.fill"
        case .ready:
            "flag.checkered"
        }
    }

    private var chipLabel: String {
        guard record.progressFraction != nil else { return "NO PROGRESS" }
        return "\(Int((progress * 100).rounded()))%"
    }

    private var progressLabel: String {
        guard record.progressFraction != nil else { return "Progress unavailable" }
        return "\(Int((progress * 100).rounded()))%"
    }

    private var stepsLabel: String {
        guard let completed = record.completedSteps, let total = record.totalSteps else {
            return "Not supplied"
        }
        return "\(completed) of \(total)"
    }

    private var activityLabel: String {
        guard let seconds = record.lastActiveSeconds else { return "Activity unavailable" }
        switch seconds {
        case 0..<60:
            return "\(seconds)s ago"
        case 60..<3_600:
            return "\(seconds / 60)m ago"
        case 3_600..<86_400:
            return "\(seconds / 3_600)h ago"
        default:
            return "\(seconds / 86_400)d ago"
        }
    }

    private var memoryLabel: String {
        guard let memory = record.memoryMB else { return "Memory unavailable" }
        if memory >= 1_024 {
            return String(format: "%.1f GB", memory / 1_024)
        }
        return "\(Int(memory.rounded())) MB"
    }

    private var cpuLabel: String {
        guard let cpu = record.cpuPercent else { return "CPU unavailable" }
        return String(format: "%.1f%% CPU", cpu)
    }

    private var hoverSummary: String {
        [
            record.title,
            record.detail,
            record.currentStep.map { "Current: \($0)" },
            "State: \(record.state.rawValue)",
            "Steps: \(stepsLabel)",
            "Progress: \(progressLabel)",
            "Last active: \(activityLabel)",
            "Memory: \(memoryLabel)",
            "CPU: \(cpuLabel)",
            "Evidence: \(record.verification.rawValue)",
        ]
        .compactMap { $0 }
        .joined(separator: "\n")
    }
}
