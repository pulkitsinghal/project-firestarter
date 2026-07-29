import CryptoKit
import Foundation

enum ReceiptFeedContractPins {
    static let reviewedSnapshotSHA256 =
        "e0c598cdcc29ba39f509ccdb553f8d2c65709896827229e3aff1ada07c1bd1f2"
    static let reviewedLKGSnapshotSHA256 =
        "ae4948b1c6396caca73a372a90474626d82d94291f36cb8bbc973799c6bebea8"
    static let feedSchemaSHA256 =
        "26cfc2cddac67831c6470f32dd54537762be95138661850d70e49a734db3ccc4"
    static let manifestSchemaSHA256 =
        "6b2649aef97774a00ed8323f91ce84c951220243ed4fd8b6d036b715d17a581f"
    static let reviewedManifestSHA256 =
        "a94a8331b303189a99334b8c2f5940418a510326ceabbc1e58c34ee2460af1f8"
    static let canonicalManifestStateSHA256 =
        "0a815cbd060d698b39badc715c16933436b7abec6588ca226bd1ffee4d73cc6a"
}

enum ReceiptFeedPointerKind: String, Hashable {
    case current
    case lkg = "last known good"
}

enum ReceiptFeedFreshness: String, Hashable {
    case current
    case stale
    case unknown
}

struct ReceiptFeedEvidence: Decodable, Hashable {
    let kind: String
    let ref: String
    let label: String?
}

struct ReceiptFeedReceipt: Identifiable, Decodable, Hashable {
    struct Metric: Decodable, Hashable {
        let value: Int?
        let availability: String
    }

    struct Duration: Decodable, Hashable {
        let estimateSeconds: Metric
        let elapsedActiveSeconds: Metric
        let externalWaitSeconds: Metric
        let firstUsefulEvidenceSeconds: Metric
    }

    struct EvidenceAge: Decodable, Hashable {
        let latestEvidenceAt: String?
        let ageSeconds: Int?
        let availability: String
    }

    let fingerprint: String
    let revision: Int
    let publicLabel: String
    let ownerClass: String
    let laneClass: String
    let metadataSource: String
    let lifecycle: String
    let gateKind: String
    let dependsOn: [String]
    let acceptanceReceipts: [String]
    let successorReceipts: [String]
    let mirrorOf: String?
    let runnable: Bool?
    let duration: Duration
    let nextSafeMove: String
    let evidenceAge: EvidenceAge
    let fieldAvailability: [String: String]
    let evidenceRefs: [ReceiptFeedEvidence]

    var id: String { fingerprint }
}

struct ReceiptFeedOwnerGate: Identifiable, Decodable, Hashable {
    let fingerprint: String
    let revision: Int
    let decisionCode: String
    let recordedAt: String
    let nextSafeMove: String
    let evidenceRefs: [ReceiptFeedEvidence]

    var id: String { fingerprint }
}

struct ReceiptFeedSource: Decodable, Hashable {
    struct Freshness: Decodable, Hashable {
        let state: String
        let ageSeconds: Int?
        let thresholdSeconds: Int
    }

    struct Provenance: Decodable, Hashable {
        let sourceClass: String
        let sanitization: String
        let rootExcluded: Bool
    }

    let generatedAt: String?
    let servedAt: String
    let sourceStatus: String
    let freshness: Freshness
    let sourceRevision: String?
    let discrepancies: [String]
    let provenance: Provenance
}

struct ReceiptFeedSnapshot: Decodable, Hashable {
    struct Capacity: Decodable, Hashable {
        let configuredWorkers: Int?
        let rootExcluded: Bool
        let availability: String
    }

    struct Counts: Decodable, Hashable {
        let availability: String
        let setupReserved: Int?
        let active: Int?
        let waiting: Int?
        let ownerGated: Int?
        let failed: Int?
        let done: Int?
        let acknowledged: Int?
        let runnable: Int?
        let quarantined: Int?
    }

    struct Quarantine: Decodable, Hashable {
        let fingerprint: String
        let reason: String
        let mirrorOf: String?
        let excludedFromCounts: Bool
    }

    let schemaVersion: String
    let source: ReceiptFeedSource
    let capacity: Capacity
    let counts: Counts
    let receipts: [ReceiptFeedReceipt]
    let ownerGates: [ReceiptFeedOwnerGate]
    let quarantine: [Quarantine]

    private enum CodingKeys: String, CodingKey {
        case schemaVersion
        case source
        case capacity
        case counts
        case receipts
        case ownerGates
        case quarantine
    }
}

struct ReceiptFeedPresentation: Hashable {
    let pointerKind: ReceiptFeedPointerKind?
    let freshness: ReceiptFeedFreshness
    let ageSeconds: Int?
    let thresholdSeconds: Int?
    let provenance: String
    let now: [ReceiptFeedReceipt]
    let decisions: [ReceiptFeedReceipt]
    let recentlyDone: [ReceiptFeedReceipt]
    let reason: String?

    static let unavailable = ReceiptFeedPresentation(
        pointerKind: nil,
        freshness: .unknown,
        ageSeconds: nil,
        thresholdSeconds: nil,
        provenance: "Receipt feed unavailable",
        now: [],
        decisions: [],
        recentlyDone: [],
        reason: "No valid current or last-known-good receipt feed is available."
    )

    var isAvailable: Bool { pointerKind != nil }

    var sourceBadge: String {
        guard let pointerKind else { return "OFFLINE" }
        if pointerKind == .lkg { return "LKG" }
        return freshness == .current ? "CURRENT" : "STALE"
    }
}

struct ReceiptFeedStore {
    enum StoreError: Error, Equatable {
        case invalidFile
        case oversized
        case invalidJSON
        case invalidPointer
        case hashMismatch
        case invalidContract
    }

    static let maximumPointerBytes = 4_096
    static let maximumSnapshotBytes = 1_048_576

    let directoryURL: URL

    init(directoryURL: URL) {
        self.directoryURL = directoryURL
    }

    func load(now: Date = Date()) -> ReceiptFeedPresentation {
        if let current = try? loadPointer(
            named: "receipt-feed-current.json",
            kind: .current,
            now: now
        ) {
            return current
        }
        if let lkg = try? loadPointer(
            named: "receipt-feed-lkg.json",
            kind: .lkg,
            now: now
        ) {
            return lkg
        }
        return .unavailable
    }

    private func loadPointer(
        named pointerName: String,
        kind: ReceiptFeedPointerKind,
        now: Date
    ) throws -> ReceiptFeedPresentation {
        let pointerData = try readRegularFile(
            directoryURL.appendingPathComponent(pointerName),
            maximumBytes: Self.maximumPointerBytes
        )
        try StrictReceiptFeedJSON.rejectDuplicateObjectKeys(in: pointerData)
        let pointerObject = try jsonObject(pointerData)
        try requireExactKeys(
            pointerObject,
            required: ["schemaVersion", "sha256", "snapshot", "generatedAt"]
        )
        guard pointerObject["schemaVersion"] as? String == "1.1",
              let digest = pointerObject["sha256"] as? String,
              digest.range(of: #"^[a-f0-9]{64}$"#, options: .regularExpression) != nil,
              let snapshotName = pointerObject["snapshot"] as? String,
              snapshotName == "receipt-feed-1.1.\(digest).json",
              let pointerGeneratedAt = pointerObject["generatedAt"] as? String,
              Self.parseDate(pointerGeneratedAt) != nil else {
            throw StoreError.invalidPointer
        }

        let snapshotData = try readRegularFile(
            directoryURL.appendingPathComponent(snapshotName),
            maximumBytes: Self.maximumSnapshotBytes
        )
        let actualDigest = SHA256.hash(data: snapshotData)
            .map { String(format: "%02x", $0) }
            .joined()
        guard actualDigest == digest else {
            throw StoreError.hashMismatch
        }

        try StrictReceiptFeedJSON.validateSnapshot(snapshotData)
        let snapshot: ReceiptFeedSnapshot
        do {
            snapshot = try JSONDecoder().decode(ReceiptFeedSnapshot.self, from: snapshotData)
        } catch {
            throw StoreError.invalidContract
        }
        try validate(snapshot)

        let freshness = Self.freshness(snapshot: snapshot, now: now)
        return ReceiptFeedPresentation(
            pointerKind: kind,
            freshness: freshness.state,
            ageSeconds: freshness.ageSeconds,
            thresholdSeconds: snapshot.source.freshness.thresholdSeconds,
            provenance:
                "\(snapshot.source.provenance.sourceClass) · "
                + "\(snapshot.source.provenance.sanitization)",
            now: snapshot.receipts.filter {
                ["active", "setup-reserved"].contains($0.lifecycle)
            },
            decisions: snapshot.receipts.filter {
                $0.lifecycle == "owner-gated" && $0.gateKind == "owner"
            },
            recentlyDone: snapshot.receipts.filter {
                ["done", "acknowledged"].contains($0.lifecycle)
            },
            reason: kind == .lkg
                ? "Current receipt feed was unavailable or invalid; showing last known good."
                : nil
        )
    }

    private func readRegularFile(_ url: URL, maximumBytes: Int) throws -> Data {
        let values: URLResourceValues
        do {
            values = try url.resourceValues(
                forKeys: [.fileSizeKey, .isRegularFileKey, .isSymbolicLinkKey]
            )
        } catch {
            throw StoreError.invalidFile
        }
        guard values.isRegularFile == true, values.isSymbolicLink != true else {
            throw StoreError.invalidFile
        }
        if let fileSize = values.fileSize, fileSize > maximumBytes {
            throw StoreError.oversized
        }
        let data: Data
        do {
            data = try Data(contentsOf: url, options: [.mappedIfSafe])
        } catch {
            throw StoreError.invalidFile
        }
        guard data.count <= maximumBytes else { throw StoreError.oversized }
        return data
    }

    private func jsonObject(_ data: Data) throws -> [String: Any] {
        let value: Any
        do {
            value = try JSONSerialization.jsonObject(with: data)
        } catch {
            throw StoreError.invalidJSON
        }
        guard let object = value as? [String: Any] else {
            throw StoreError.invalidJSON
        }
        return object
    }

    private func requireExactKeys(
        _ object: [String: Any],
        required: Set<String>,
        optional: Set<String> = []
    ) throws {
        guard Set(object.keys).isSuperset(of: required),
              Set(object.keys).subtracting(required).isSubset(of: optional) else {
            throw StoreError.invalidContract
        }
    }

    private func validate(_ snapshot: ReceiptFeedSnapshot) throws {
        guard snapshot.schemaVersion == "1.1",
              snapshot.capacity.rootExcluded,
              snapshot.source.provenance.rootExcluded,
              [
                "orchestrator-status", "orchestrator-ledger", "pm-proxy-manifest",
                "legacy-receipt-feed",
              ].contains(snapshot.source.provenance.sourceClass),
              [
                "projection-enforced", "caller-allowlisted+projection-validated",
                "migration-placeholder",
              ].contains(snapshot.source.provenance.sanitization),
              ["live", "degraded"].contains(
                snapshot.source.sourceStatus
              ),
              ["current", "stale", "unknown"].contains(snapshot.source.freshness.state),
              snapshot.source.freshness.thresholdSeconds > 0,
              snapshot.receipts.count <= 2_000,
              snapshot.ownerGates.count <= 2_000,
              snapshot.quarantine.count <= 2_000,
              Self.validOptionalNonnegative(snapshot.capacity.configuredWorkers),
              ["supplied", "derived", "unavailable"].contains(
                snapshot.capacity.availability
              ),
              Self.validCounts(snapshot.counts),
              Self.validDiscrepancies(snapshot.source.discrepancies),
              Self.parseDate(snapshot.source.servedAt) != nil,
              (
                  snapshot.source.generatedAt == nil
                      || snapshot.source.generatedAt.flatMap(Self.parseDate) != nil
              ) else {
            throw StoreError.invalidContract
        }
        if let revision = snapshot.source.sourceRevision {
            guard revision.range(
                of: #"^[A-Za-z0-9._:-]{1,128}$"#,
                options: .regularExpression
            ) != nil else {
                throw StoreError.invalidContract
            }
        }
        guard snapshot.receipts.allSatisfy(Self.validReceipt),
              snapshot.ownerGates.allSatisfy(Self.validOwnerGate),
              snapshot.quarantine.allSatisfy(Self.validQuarantine) else {
            throw StoreError.invalidContract
        }
    }

    private static func validOptionalNonnegative(_ value: Int?) -> Bool {
        value.map { $0 >= 0 } ?? true
    }

    private static func validDiscrepancies(_ values: [String]) -> Bool {
        values.count <= 16
            && Set(values).count == values.count
            && values.allSatisfy {
                [
                    "CAPACITY_INVARIANT_FAILED", "MIRROR_QUARANTINED",
                    "RECEIPT_REVISION_CONFLICT", "STALE_SOURCE",
                    "SUPPLIED_DERIVED_MISMATCH",
                ].contains($0)
            }
    }

    private static func validCounts(_ counts: ReceiptFeedSnapshot.Counts) -> Bool {
        ["derived", "unavailable"].contains(counts.availability)
            && [
                counts.setupReserved, counts.active, counts.waiting,
                counts.ownerGated, counts.failed, counts.done,
                counts.acknowledged, counts.runnable, counts.quarantined,
            ].allSatisfy(validOptionalNonnegative)
    }

    private static func validReceipt(_ receipt: ReceiptFeedReceipt) -> Bool {
        receipt.fingerprint.range(
            of: #"^rcpt_[a-f0-9]{64}$"#,
            options: .regularExpression
        ) != nil
            && receipt.revision > 0
            && receipt.publicLabel.range(
                of: #"^[A-Za-z0-9][A-Za-z0-9 .,&()'’+-]{0,79}$"#,
                options: .regularExpression
            ) != nil
            && ["pm-proxy", "worker", "owner", "external", "unknown"].contains(
                receipt.ownerClass
            )
            && ["running", "next", "waiting", "owner-gated", "complete", "unknown"]
                .contains(receipt.laneClass)
            && ["launch", "handback", "migration", "unavailable"].contains(
                receipt.metadataSource
            )
            && [
                "setup-reserved", "active", "waiting", "owner-gated", "failed",
                "done", "acknowledged",
            ].contains(receipt.lifecycle)
            && ["none", "dependency", "owner", "external", "capacity", "failure"]
                .contains(receipt.gateKind)
            && validFingerprintArray(receipt.dependsOn)
            && validFingerprintArray(receipt.acceptanceReceipts)
            && validFingerprintArray(receipt.successorReceipts)
            && (receipt.mirrorOf.map(validFingerprint) ?? true)
            && validDuration(receipt.duration)
            && [
                "await-launch-receipt", "continue-active-work",
                "resolve-dependency", "review-owner-gate",
                "retry-or-reconcile-failure", "verify-and-archive",
                "none-terminal",
            ].contains(receipt.nextSafeMove)
            && validEvidenceAge(receipt.evidenceAge)
            && !receipt.fieldAvailability.isEmpty
            && receipt.fieldAvailability.values.allSatisfy {
                ["supplied", "derived", "unavailable"].contains($0)
            }
            && receipt.evidenceRefs.count <= 24
            && receipt.evidenceRefs.allSatisfy(validEvidence)
    }

    private static func validFingerprint(_ value: String) -> Bool {
        value.range(of: #"^rcpt_[a-f0-9]{64}$"#, options: .regularExpression) != nil
    }

    private static func validFingerprintArray(_ values: [String]) -> Bool {
        Set(values).count == values.count && values.allSatisfy(validFingerprint)
    }

    private static func validDuration(_ duration: ReceiptFeedReceipt.Duration) -> Bool {
        [
            duration.estimateSeconds, duration.elapsedActiveSeconds,
            duration.externalWaitSeconds, duration.firstUsefulEvidenceSeconds,
        ].allSatisfy {
            validOptionalNonnegative($0.value)
                && ["supplied", "derived", "unavailable"].contains($0.availability)
        }
    }

    private static func validEvidenceAge(_ age: ReceiptFeedReceipt.EvidenceAge) -> Bool {
        (
            age.latestEvidenceAt == nil
                || age.latestEvidenceAt.flatMap(parseDate) != nil
        )
            && validOptionalNonnegative(age.ageSeconds)
            && ["derived", "unavailable"].contains(age.availability)
    }

    private static func validOwnerGate(_ gate: ReceiptFeedOwnerGate) -> Bool {
        gate.fingerprint.range(
            of: #"^rcpt_[a-f0-9]{64}$"#,
            options: .regularExpression
        ) != nil
            && gate.revision > 0
            && gate.decisionCode.range(
                of: #"^[A-Z][A-Z0-9_]{0,127}$"#,
                options: .regularExpression
            ) != nil
            && parseDate(gate.recordedAt) != nil
            && gate.nextSafeMove == "review-owner-gate"
            && !gate.evidenceRefs.isEmpty
            && gate.evidenceRefs.count <= 24
            && gate.evidenceRefs.allSatisfy(validEvidence)
    }

    private static func validQuarantine(
        _ item: ReceiptFeedSnapshot.Quarantine
    ) -> Bool {
        validFingerprint(item.fingerprint)
            && [
                "duplicate-without-mirrorOf", "mirror", "revision-conflict",
                "invalid", "privacy-rejected",
            ].contains(item.reason)
            && (item.mirrorOf.map(validFingerprint) ?? true)
            && item.excludedFromCounts
    }

    private static func validEvidence(_ evidence: ReceiptFeedEvidence) -> Bool {
        ["receipt", "test", "commit", "pullRequest", "deployment", "decision", "artifact"]
            .contains(evidence.kind)
            && evidence.ref.range(
                of: #"^[A-Za-z0-9][A-Za-z0-9._:/#@+-]{0,159}$"#,
                options: .regularExpression
            ) != nil
            && !evidence.ref.contains("/Users/")
            && !evidence.ref.contains("/private/")
            && !evidence.ref.lowercased().hasPrefix("file:")
            && (evidence.label.map {
                !$0.contains("\n") && !$0.contains("\r") && !$0.contains("<")
                    && !$0.contains(">") && $0.count <= 120
            } ?? true)
    }

    private static func freshness(
        snapshot: ReceiptFeedSnapshot,
        now: Date
    ) -> (state: ReceiptFeedFreshness, ageSeconds: Int?) {
        guard let generatedAt = snapshot.source.generatedAt,
              let generated = parseDate(generatedAt) else {
            return (.unknown, nil)
        }
        let age = max(0, now.timeIntervalSince(generated))
        let roundedUp = Int(ceil(age))
        return (
            roundedUp > snapshot.source.freshness.thresholdSeconds ? .stale : .current,
            roundedUp
        )
    }

    private static func parseDate(_ value: String) -> Date? {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let parsed = formatter.date(from: value) { return parsed }
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: value)
    }
}

private enum StrictReceiptFeedJSON {
    static func validateSnapshot(_ data: Data) throws {
        try rejectDuplicateObjectKeys(in: data)
        let value: Any
        do {
            value = try JSONSerialization.jsonObject(with: data)
        } catch {
            throw ReceiptFeedStore.StoreError.invalidJSON
        }
        guard let root = value as? [String: Any] else {
            throw ReceiptFeedStore.StoreError.invalidContract
        }
        try exact(root, ["schemaVersion", "source", "capacity", "counts", "receipts",
                         "ownerGates", "quarantine"])
        try exactObject(
            root["source"],
            ["generatedAt", "servedAt", "sourceStatus", "freshness", "sourceRevision",
             "discrepancies", "provenance"]
        )
        let source = try object(root["source"])
        try exactObject(source["freshness"], ["state", "ageSeconds", "thresholdSeconds"])
        try exactObject(
            source["provenance"],
            ["sourceClass", "sanitization", "rootExcluded"]
        )
        try exactObject(
            root["capacity"],
            ["configuredWorkers", "rootExcluded", "availability"]
        )
        try exactObject(
            root["counts"],
            ["availability", "setupReserved", "active", "waiting", "ownerGated",
             "failed", "done", "acknowledged", "runnable", "quarantined"]
        )
        for receipt in try array(root["receipts"]) {
            let item = try object(receipt)
            try exact(
                item,
                ["fingerprint", "revision", "publicLabel", "ownerClass", "laneClass",
                 "metadataSource", "lifecycle", "gateKind", "dependsOn",
                 "acceptanceReceipts", "successorReceipts", "runnable", "duration",
                 "nextSafeMove", "evidenceAge", "fieldAvailability", "evidenceRefs"],
                optional: ["mirrorOf"]
            )
            let duration = try object(item["duration"])
            try exact(
                duration,
                ["estimateSeconds", "elapsedActiveSeconds", "externalWaitSeconds",
                 "firstUsefulEvidenceSeconds"]
            )
            for metric in duration.values {
                try exactObject(metric, ["value", "availability"])
            }
            try exactObject(
                item["evidenceAge"],
                ["latestEvidenceAt", "ageSeconds", "availability"]
            )
            guard let availability = item["fieldAvailability"] as? [String: Any],
                  !availability.isEmpty,
                  availability.values.allSatisfy({
                      guard let value = $0 as? String else { return false }
                      return ["supplied", "derived", "unavailable"].contains(value)
                  }) else {
                throw ReceiptFeedStore.StoreError.invalidContract
            }
            try validateEvidence(item["evidenceRefs"])
        }
        for gate in try array(root["ownerGates"]) {
            let item = try object(gate)
            try exact(
                item,
                ["fingerprint", "revision", "decisionCode", "recordedAt",
                 "nextSafeMove", "evidenceRefs"]
            )
            try validateEvidence(item["evidenceRefs"])
        }
        for quarantine in try array(root["quarantine"]) {
            try exact(
                try object(quarantine),
                ["fingerprint", "reason", "excludedFromCounts"],
                optional: ["mirrorOf"]
            )
        }
    }

    static func rejectDuplicateObjectKeys(in data: Data) throws {
        guard let text = String(data: data, encoding: .utf8) else {
            throw ReceiptFeedStore.StoreError.invalidJSON
        }
        var parser = JSONKeyParser(text)
        try parser.parse()
    }

    private static func validateEvidence(_ value: Any?) throws {
        for evidence in try array(value) {
            try exact(
                try object(evidence),
                ["kind", "ref"],
                optional: ["label"]
            )
        }
    }

    private static func exactObject(_ value: Any?, _ keys: Set<String>) throws {
        try exact(try object(value), keys)
    }

    private static func exact(
        _ object: [String: Any],
        _ required: Set<String>,
        optional: Set<String> = []
    ) throws {
        let keys = Set(object.keys)
        guard keys.isSuperset(of: required),
              keys.subtracting(required).isSubset(of: optional) else {
            throw ReceiptFeedStore.StoreError.invalidContract
        }
    }

    private static func object(_ value: Any?) throws -> [String: Any] {
        guard let object = value as? [String: Any] else {
            throw ReceiptFeedStore.StoreError.invalidContract
        }
        return object
    }

    private static func array(_ value: Any?) throws -> [Any] {
        guard let array = value as? [Any], array.count <= 2_000 else {
            throw ReceiptFeedStore.StoreError.invalidContract
        }
        return array
    }
}

private struct JSONKeyParser {
    private let scalars: [UnicodeScalar]
    private var index = 0

    init(_ text: String) {
        scalars = Array(text.unicodeScalars)
    }

    mutating func parse() throws {
        skipWhitespace()
        try value()
        skipWhitespace()
        guard index == scalars.count else { throw ReceiptFeedStore.StoreError.invalidJSON }
    }

    private mutating func value() throws {
        skipWhitespace()
        guard let scalar = peek() else { throw ReceiptFeedStore.StoreError.invalidJSON }
        switch scalar {
        case "{": try object()
        case "[": try array()
        case "\"": _ = try string()
        case "t": try literal("true")
        case "f": try literal("false")
        case "n": try literal("null")
        default: try number()
        }
    }

    private mutating func object() throws {
        try consume("{")
        skipWhitespace()
        if consumeIf("}") { return }
        var keys = Set<String>()
        while true {
            skipWhitespace()
            let key = try string()
            guard keys.insert(key).inserted else {
                throw ReceiptFeedStore.StoreError.invalidJSON
            }
            skipWhitespace()
            try consume(":")
            try value()
            skipWhitespace()
            if consumeIf("}") { return }
            try consume(",")
        }
    }

    private mutating func array() throws {
        try consume("[")
        skipWhitespace()
        if consumeIf("]") { return }
        while true {
            try value()
            skipWhitespace()
            if consumeIf("]") { return }
            try consume(",")
        }
    }

    private mutating func string() throws -> String {
        try consume("\"")
        var result = ""
        while let scalar = peek() {
            index += 1
            if scalar == "\"" { return result }
            if scalar == "\\" {
                guard let escaped = peek() else {
                    throw ReceiptFeedStore.StoreError.invalidJSON
                }
                index += 1
                if escaped == "u" {
                    guard index + 4 <= scalars.count else {
                        throw ReceiptFeedStore.StoreError.invalidJSON
                    }
                    let digits = String(String.UnicodeScalarView(scalars[index..<(index + 4)]))
                    guard let value = UInt32(digits, radix: 16),
                          let decoded = UnicodeScalar(value) else {
                        throw ReceiptFeedStore.StoreError.invalidJSON
                    }
                    result.unicodeScalars.append(decoded)
                    index += 4
                } else {
                    let mapped: UnicodeScalar
                    switch escaped {
                    case "\"", "\\", "/": mapped = escaped
                    case "b": mapped = "\u{8}"
                    case "f": mapped = "\u{c}"
                    case "n": mapped = "\n"
                    case "r": mapped = "\r"
                    case "t": mapped = "\t"
                    default: throw ReceiptFeedStore.StoreError.invalidJSON
                    }
                    result.unicodeScalars.append(mapped)
                }
            } else {
                guard scalar.value >= 0x20 else {
                    throw ReceiptFeedStore.StoreError.invalidJSON
                }
                result.unicodeScalars.append(scalar)
            }
        }
        throw ReceiptFeedStore.StoreError.invalidJSON
    }

    private mutating func number() throws {
        let start = index
        while let scalar = peek(),
              "-+0123456789.eE".unicodeScalars.contains(scalar) {
            index += 1
        }
        guard index > start else { throw ReceiptFeedStore.StoreError.invalidJSON }
    }

    private mutating func literal(_ expected: String) throws {
        for scalar in expected.unicodeScalars {
            try consume(scalar)
        }
    }

    private mutating func consume(_ expected: UnicodeScalar) throws {
        guard peek() == expected else { throw ReceiptFeedStore.StoreError.invalidJSON }
        index += 1
    }

    private mutating func consumeIf(_ expected: UnicodeScalar) -> Bool {
        guard peek() == expected else { return false }
        index += 1
        return true
    }

    private mutating func skipWhitespace() {
        while let scalar = peek(), " \n\r\t".unicodeScalars.contains(scalar) {
            index += 1
        }
    }

    private func peek() -> UnicodeScalar? {
        index < scalars.count ? scalars[index] : nil
    }
}
