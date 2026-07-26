import Foundation

enum DashboardExposure: String, Decodable, Hashable {
    case sanitized
    case localOnly = "local-only"
}

enum DashboardVerification: String, Decodable, Hashable {
    case verified
    case estimated
    case unavailable
    case notImplemented = "not-implemented"
}

struct QueueRecord: Identifiable, Decodable, Hashable {
    enum State: String, Decodable, Hashable {
        case running
        case queued
        case waiting
        case ready
    }

    let id: String
    let title: String
    let detail: String
    let state: State
    let exposure: DashboardExposure
    let verification: DashboardVerification
}

struct TestRecord: Identifiable, Decodable, Hashable {
    enum Result: String, Decodable, Hashable {
        case passed
        case failed
        case queued
        case notRun = "not-run"
        case notImplemented = "not-implemented"
        case unknown
    }

    let id: String
    let title: String
    let detail: String
    let result: Result
    let exposure: DashboardExposure
    let verification: DashboardVerification
}

struct ResourceBudgetRecord: Identifiable, Decodable, Hashable {
    let id: String
    let title: String
    let detail: String
    let displayValue: String
    let value: Double?
    let capacity: Double?
    let exposure: DashboardExposure
    let verification: DashboardVerification

    init(
        id: String,
        title: String,
        detail: String,
        displayValue: String,
        value: Double? = nil,
        capacity: Double? = nil,
        exposure: DashboardExposure,
        verification: DashboardVerification
    ) {
        self.id = id
        self.title = title
        self.detail = detail
        self.displayValue = displayValue
        self.value = value
        self.capacity = capacity
        self.exposure = exposure
        self.verification = verification
    }
}

struct SignalRecord: Identifiable, Decodable, Hashable {
    enum State: String, Decodable, Hashable {
        case available
        case attention
        case unavailable
        case unknown
    }

    let id: String
    let title: String
    let detail: String
    let state: State
    let exposure: DashboardExposure
    let verification: DashboardVerification
}

struct DashboardSnapshot: Decodable, Hashable {
    enum Mode: String, Decodable, Hashable {
        case sample
        case local
        case sanitizedRemote = "sanitized-remote"
    }

    enum ValidationError: Error {
        case unsupportedVersion
        case unsupportedStructure
        case privateRecordInSanitizedSnapshot
        case unverifiedLocalRecord
        case invalidResourceBudget
    }

    let schemaVersion: String
    let mode: Mode
    let queue: [QueueRecord]
    let tests: [TestRecord]
    let resourceBudget: [ResourceBudgetRecord]
    let signals: [SignalRecord]

    static func decodeValidated(from data: Data) throws -> DashboardSnapshot {
        let object = try JSONSerialization.jsonObject(with: data)
        guard let root = object as? [String: Any] else {
            throw ValidationError.unsupportedStructure
        }

        try requireKeys(
            in: root,
            required: ["schemaVersion", "mode", "queue", "tests", "resourceBudget", "signals"]
        )
        try requireRecordKeys(
            root["queue"],
            required: ["id", "title", "detail", "state", "exposure", "verification"]
        )
        try requireRecordKeys(
            root["tests"],
            required: ["id", "title", "detail", "result", "exposure", "verification"]
        )
        try requireRecordKeys(
            root["resourceBudget"],
            required: ["id", "title", "detail", "displayValue", "exposure", "verification"],
            optional: ["value", "capacity"]
        )
        try requireRecordKeys(
            root["signals"],
            required: ["id", "title", "detail", "state", "exposure", "verification"]
        )

        return try JSONDecoder().decode(DashboardSnapshot.self, from: data).validatedForNative()
    }

    func validatedForNative() throws -> DashboardSnapshot {
        guard schemaVersion == "1.0" else {
            throw ValidationError.unsupportedVersion
        }

        let exposureAndVerification =
            queue.map { ($0.exposure, $0.verification) }
            + tests.map { ($0.exposure, $0.verification) }
            + resourceBudget.map { ($0.exposure, $0.verification) }
            + signals.map { ($0.exposure, $0.verification) }

        if mode != .local {
            guard exposureAndVerification.allSatisfy({ $0.0 == .sanitized }) else {
                throw ValidationError.privateRecordInSanitizedSnapshot
            }
        }

        guard exposureAndVerification.allSatisfy({
            $0.0 != .localOnly || $0.1 == .verified
        }) else {
            throw ValidationError.unverifiedLocalRecord
        }

        guard resourceBudget.allSatisfy({
            ($0.value ?? 0) >= 0 && ($0.capacity.map { $0 > 0 } ?? true)
        }) else {
            throw ValidationError.invalidResourceBudget
        }

        return self
    }

    static let sample = DashboardSnapshot(
        schemaVersion: "1.0",
        mode: .sample,
        queue: [
            QueueRecord(
                id: "EX-Q1",
                title: "Example work item",
                detail: "Replace with approved local or sanitized state.",
                state: .running,
                exposure: .sanitized,
                verification: .estimated
            ),
            QueueRecord(
                id: "EX-Q2",
                title: "Example queued item",
                detail: "Awaiting a generic follow-up.",
                state: .queued,
                exposure: .sanitized,
                verification: .estimated
            )
        ],
        tests: [
            TestRecord(
                id: "EX-T1",
                title: "Example contract check",
                detail: "No executed result is claimed in the committed fixture.",
                result: .notRun,
                exposure: .sanitized,
                verification: .unavailable
            )
        ],
        resourceBudget: [
            ResourceBudgetRecord(
                id: "EX-R1",
                title: "Heavy validation lane",
                detail: "Run one heavyweight validation at a time.",
                displayValue: "Not supplied",
                exposure: .sanitized,
                verification: .unavailable
            )
        ],
        signals: [
            SignalRecord(
                id: "EX-S1",
                title: "Example local signal",
                detail: "Runtime values are intentionally absent from the committed fixture.",
                state: .unavailable,
                exposure: .sanitized,
                verification: .notImplemented
            )
        ]
    )

    private static func requireKeys(
        in object: [String: Any],
        required: Set<String>,
        optional: Set<String> = []
    ) throws {
        let actual = Set(object.keys)
        guard required.isSubset(of: actual), actual.isSubset(of: required.union(optional)) else {
            throw ValidationError.unsupportedStructure
        }
    }

    private static func requireRecordKeys(
        _ value: Any?,
        required: Set<String>,
        optional: Set<String> = []
    ) throws {
        guard let records = value as? [[String: Any]] else {
            throw ValidationError.unsupportedStructure
        }
        try records.forEach { try requireKeys(in: $0, required: required, optional: optional) }
    }
}
