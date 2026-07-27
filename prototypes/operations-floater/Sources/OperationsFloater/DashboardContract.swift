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
    let completedSteps: Int?
    let totalSteps: Int?
    let currentStep: String?
    let lastActiveSeconds: Int?
    let memoryMB: Double?
    let cpuPercent: Double?

    init(
        id: String,
        title: String,
        detail: String,
        state: State,
        exposure: DashboardExposure,
        verification: DashboardVerification,
        completedSteps: Int? = nil,
        totalSteps: Int? = nil,
        currentStep: String? = nil,
        lastActiveSeconds: Int? = nil,
        memoryMB: Double? = nil,
        cpuPercent: Double? = nil
    ) {
        self.id = id
        self.title = title
        self.detail = detail
        self.state = state
        self.exposure = exposure
        self.verification = verification
        self.completedSteps = completedSteps
        self.totalSteps = totalSteps
        self.currentStep = currentStep
        self.lastActiveSeconds = lastActiveSeconds
        self.memoryMB = memoryMB
        self.cpuPercent = cpuPercent
    }

    var progressFraction: Double? {
        guard let completedSteps, let totalSteps, totalSteps > 0 else { return nil }
        return min(1, max(0, Double(completedSteps) / Double(totalSteps)))
    }
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
        case invalidRecordContent
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
            required: ["id", "title", "detail", "state", "exposure", "verification"],
            optional: [
                "completedSteps",
                "totalSteps",
                "currentStep",
                "lastActiveSeconds",
                "memoryMB",
                "cpuPercent",
            ]
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
        guard queue.count <= 100,
              tests.count <= 100,
              resourceBudget.count <= 50,
              signals.count <= 100 else {
            throw ValidationError.invalidRecordContent
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
        guard queue.allSatisfy({ record in
            let stepsArePaired = (record.completedSteps == nil) == (record.totalSteps == nil)
            let stepsAreValid =
                record.completedSteps.map { $0 >= 0 && $0 <= 100_000 } ?? true
            let totalIsValid = record.totalSteps.map { $0 > 0 && $0 <= 100_000 } ?? true
            let completedFitsTotal =
                if let completed = record.completedSteps, let total = record.totalSteps {
                    completed <= total
                } else {
                    true
                }
            return stepsArePaired
                && stepsAreValid
                && totalIsValid
                && completedFitsTotal
                && (record.lastActiveSeconds.map { $0 >= 0 && $0 <= 315_360_000 } ?? true)
                && (record.memoryMB.map { $0 >= 0 && $0 <= 16_777_216 } ?? true)
                && (record.cpuPercent.map { $0 >= 0 && $0 <= 100 } ?? true)
        }) else {
            throw ValidationError.invalidRecordContent
        }

        let commonFields =
            queue.map { ($0.id, $0.title, $0.detail) }
            + tests.map { ($0.id, $0.title, $0.detail) }
            + resourceBudget.map { ($0.id, $0.title, $0.detail) }
            + signals.map { ($0.id, $0.title, $0.detail) }
        guard commonFields.allSatisfy({
            Self.isValidIdentifier($0.0)
                && Self.isValidString($0.1, maximum: 120)
                && Self.isValidString($0.2, maximum: 240)
        }),
        resourceBudget.allSatisfy({
            Self.isValidString($0.displayValue, maximum: 80)
        }),
        queue.allSatisfy({
            $0.currentStep.map { Self.isValidString($0, maximum: 120) } ?? true
        }) else {
            throw ValidationError.invalidRecordContent
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
                verification: .estimated,
                completedSteps: 5,
                totalSteps: 8,
                currentStep: "Verifying the bounded build",
                lastActiveSeconds: 18,
                memoryMB: 2_450,
                cpuPercent: 36.5
            ),
            QueueRecord(
                id: "EX-Q2",
                title: "Example queued item",
                detail: "Awaiting a generic follow-up.",
                state: .queued,
                exposure: .sanitized,
                verification: .estimated,
                completedSteps: 1,
                totalSteps: 6,
                currentStep: "Waiting for a worker slot",
                lastActiveSeconds: 240,
                memoryMB: 180,
                cpuPercent: 0.4
            ),
            QueueRecord(
                id: "EX-Q3",
                title: "Example dependency review",
                detail: "A synthetic dependency added two more steps.",
                state: .waiting,
                exposure: .sanitized,
                verification: .estimated,
                completedSteps: 3,
                totalSteps: 9,
                currentStep: "Resolve the added dependency",
                lastActiveSeconds: 900,
                memoryMB: 620,
                cpuPercent: 1.2
            ),
            QueueRecord(
                id: "EX-Q4",
                title: "Example ready item",
                detail: "Synthetic work completed every declared step.",
                state: .ready,
                exposure: .sanitized,
                verification: .estimated,
                completedSteps: 8,
                totalSteps: 8,
                currentStep: "Ready for owner review",
                lastActiveSeconds: 45,
                memoryMB: 96,
                cpuPercent: 0
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

    private static func isValidIdentifier(_ value: String) -> Bool {
        value.range(
            of: #"^[A-Za-z0-9][A-Za-z0-9-]{0,63}$"#,
            options: .regularExpression
        ) != nil
    }

    private static func isValidString(_ value: String, maximum: Int) -> Bool {
        !value.isEmpty && value.utf16.count <= maximum
    }
}
