import Combine
import Foundation

enum ConversationModuleContract {
    static let version = "1.0"
    static let clientIdentifier = "operations-floater"
    static let loopbackBaseURL = URL(
        string: "http://127.0.0.1:11510/v1/conversation-modules"
    )!

    static let maximumNarrationCharacters = 2_000
    static let maximumContextTurns = 6
    static let maximumContextCharacters = 6_000
    static let maximumEvents = 32
    static let maximumReplyCharacters = 4_000
    static let maximumQuestionCharacters = 600
    static let maximumStatuses = 4
    static let maximumCheckpoints = 8
    static let maximumProposedActions = 4
    static let maximumResponseBytes = 65_536
    static let maximumHealthBytes = 16_384
}

enum ConversationModuleCapability: String, Codable, CaseIterable, Sendable {
    case narration
    case normalizedPointerEvents = "normalized-pointer-events"
    case navigationKeys = "navigation-keys"
    case rawKeyboardEvents = "raw-keyboard-events"
    case scrollEvents = "scroll-events"
    case placeholderEvents = "placeholder-events"
    case neutralWindowContext = "neutral-window-context"
    case checkpoints
    case proposedActions = "proposed-actions"
}

struct ConversationModulePrivacy: Codable, Equatable, Sendable {
    let ephemeralOnly: Bool
    let moduleOwnsMicrophone: Bool
    let moduleOwnsUI: Bool
    let moduleOwnsTTS: Bool
    let arbitraryNetwork: Bool
    let persistence: Bool
    let screenCapture: Bool
    let inputInjection: Bool
    let executableReplay: Bool

    static let hostControlled = ConversationModulePrivacy(
        ephemeralOnly: true,
        moduleOwnsMicrophone: false,
        moduleOwnsUI: false,
        moduleOwnsTTS: false,
        arbitraryNetwork: false,
        persistence: false,
        screenCapture: false,
        inputInjection: false,
        executableReplay: false
    )

    func validate() throws {
        guard self == .hostControlled else {
            throw ConversationModuleError.privacyContractRejected
        }
    }
}

struct ConversationModuleManifest: Codable, Equatable, Identifiable, Sendable {
    let contractVersion: String
    let moduleID: String
    let displayName: String
    let capabilities: [ConversationModuleCapability]
    let privacy: ConversationModulePrivacy
    let provenanceSourceID: String
    let allowedTranscriptProviders: [ConversationTranscriptProvider]
    let allowedWindowBindingIDs: [String]

    var id: String { moduleID }

    func validate() throws {
        guard contractVersion == ConversationModuleContract.version else {
            throw ConversationModuleError.unsupportedContract
        }
        guard Self.validIdentifier(moduleID, maximum: 120),
              Self.validIdentifier(provenanceSourceID, maximum: 120),
              !displayName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              displayName.count <= 80,
              Set(capabilities).count == capabilities.count,
              !capabilities.isEmpty,
              !allowedTranscriptProviders.isEmpty,
              Set(allowedTranscriptProviders).count == allowedTranscriptProviders.count,
              Set(allowedWindowBindingIDs).count == allowedWindowBindingIDs.count,
              allowedWindowBindingIDs.count <= 8,
              allowedWindowBindingIDs.allSatisfy({
                  Self.validIdentifier($0, maximum: 120)
              }),
              capabilities.contains(.neutralWindowContext)
                == !allowedWindowBindingIDs.isEmpty else {
            throw ConversationModuleError.invalidManifest
        }
        try privacy.validate()
    }

    static func validIdentifier(_ value: String, maximum: Int) -> Bool {
        guard value.count <= maximum else { return false }
        return value.range(
            of: #"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$"#,
            options: .regularExpression
        ) != nil
    }
}

struct ConversationModuleProvenance: Codable, Equatable, Sendable {
    let sourceID: String
    let buildDigest: String

    func validate(expectedSourceID: String) throws {
        guard sourceID == expectedSourceID,
              buildDigest.range(
                  of: #"^[a-f0-9]{64}$"#,
                  options: .regularExpression
              ) != nil else {
            throw ConversationModuleError.provenanceMismatch
        }
    }
}

enum ConversationModuleHealthState: String, Codable, Sendable {
    case ready
    case degraded
    case unavailable
}

struct ConversationModuleHealth: Codable, Equatable, Sendable {
    let contractVersion: String
    let moduleID: String
    let state: ConversationModuleHealthState
    let privacy: ConversationModulePrivacy
    let provenance: ConversationModuleProvenance

    func validate(for manifest: ConversationModuleManifest) throws {
        try manifest.validate()
        guard contractVersion == manifest.contractVersion,
              moduleID == manifest.moduleID,
              privacy == manifest.privacy else {
            throw ConversationModuleError.healthMismatch
        }
        try privacy.validate()
        try provenance.validate(expectedSourceID: manifest.provenanceSourceID)
    }
}

enum ConversationFloorState: String, Codable, Sendable {
    case granted
    case revoked
}

struct ConversationFloorGrant: Codable, Equatable, Sendable {
    let state: ConversationFloorState
    let moduleID: String
    let token: String

    func validate(expectedModuleID: String, expectedState: ConversationFloorState) throws {
        guard state == expectedState,
              moduleID == expectedModuleID,
              token.range(
                  of: #"^floor_[a-f0-9-]{36}$"#,
                  options: .regularExpression
              ) != nil else {
            throw ConversationModuleError.floorMismatch
        }
    }
}

enum ConversationTranscriptProvider: String, Codable, Hashable, Sendable {
    case typedKeyboard = "typed-keyboard"
    case onDevice
    case syntheticFixture
}

enum ConversationModuleRequestKind: String, Codable, Sendable {
    case turn
    case revoke
    case end
}

enum ConversationModuleContextRole: String, Codable, Sendable {
    case user
    case module
}

struct ConversationModuleContextTurn: Codable, Equatable, Sendable {
    let role: ConversationModuleContextRole
    let text: String

    func validate() throws {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed.count <= 1_000 else {
            throw ConversationModuleError.contextTooLarge
        }
    }
}

struct ConversationModuleContext: Codable, Equatable, Sendable {
    let turns: [ConversationModuleContextTurn]

    static let empty = ConversationModuleContext(turns: [])

    func validate() throws {
        guard turns.count <= ConversationModuleContract.maximumContextTurns,
              turns.reduce(0, { $0 + $1.text.count })
                <= ConversationModuleContract.maximumContextCharacters else {
            throw ConversationModuleError.contextTooLarge
        }
        try turns.forEach { try $0.validate() }
    }
}

enum ConversationPointerPhase: String, Codable, Sendable {
    case move
    case down
    case up
    case drag
}

enum ConversationKeyPhase: String, Codable, Sendable {
    case down
    case up
    case flagsChanged = "flags-changed"
}

enum ConversationNavigationKey: String, Codable, Sendable {
    case tab
    case returnKey = "return"
    case space
    case arrowLeft = "arrow-left"
    case arrowRight = "arrow-right"
    case arrowUp = "arrow-up"
    case arrowDown = "arrow-down"
    case delete
}

enum ConversationPlaceholderKind: String, Codable, Sendable {
    case primaryAction = "primary-action"
    case secondaryAction = "secondary-action"
    case textField = "text-field"
    case canvasRegion = "canvas-region"
}

enum ConversationModuleEventKind: String, Codable, Sendable {
    case normalizedPointer = "normalized-pointer"
    case navigationKey = "navigation-key"
    case rawKeyboard = "raw-keyboard"
    case scroll
    case placeholder
}

struct ConversationModuleEvent: Codable, Equatable, Sendable {
    let eventID: String
    let sequence: Int
    let kind: ConversationModuleEventKind
    let pointerPhase: ConversationPointerPhase?
    let normalizedX: Double?
    let normalizedY: Double?
    let navigationKey: ConversationNavigationKey?
    let keyPhase: ConversationKeyPhase?
    let keyCode: Int?
    let modifierFlags: UInt64?
    let buttonNumber: Int?
    let scrollDeltaX: Double?
    let scrollDeltaY: Double?
    let elapsedMilliseconds: Int?
    let placeholder: ConversationPlaceholderKind?

    init(
        eventID: String,
        sequence: Int,
        kind: ConversationModuleEventKind,
        pointerPhase: ConversationPointerPhase? = nil,
        normalizedX: Double? = nil,
        normalizedY: Double? = nil,
        navigationKey: ConversationNavigationKey? = nil,
        keyPhase: ConversationKeyPhase? = nil,
        keyCode: Int? = nil,
        modifierFlags: UInt64? = nil,
        buttonNumber: Int? = nil,
        scrollDeltaX: Double? = nil,
        scrollDeltaY: Double? = nil,
        elapsedMilliseconds: Int? = nil,
        placeholder: ConversationPlaceholderKind? = nil
    ) {
        self.eventID = eventID
        self.sequence = sequence
        self.kind = kind
        self.pointerPhase = pointerPhase
        self.normalizedX = normalizedX
        self.normalizedY = normalizedY
        self.navigationKey = navigationKey
        self.keyPhase = keyPhase
        self.keyCode = keyCode
        self.modifierFlags = modifierFlags
        self.buttonNumber = buttonNumber
        self.scrollDeltaX = scrollDeltaX
        self.scrollDeltaY = scrollDeltaY
        self.elapsedMilliseconds = elapsedMilliseconds
        self.placeholder = placeholder
    }

    func validate() throws {
        guard eventID.range(
            of: #"^event_[a-z0-9-]{1,64}$"#,
            options: .regularExpression
        ) != nil,
              sequence >= 1 else {
            throw ConversationModuleError.invalidEvent
        }
        switch kind {
        case .normalizedPointer:
            guard pointerPhase != nil,
                  let normalizedX,
                  let normalizedY,
                  (0...1).contains(normalizedX),
                  (0...1).contains(normalizedY),
                  navigationKey == nil,
                  keyPhase == nil,
                  keyCode == nil,
                  buttonNumber.map({ (0...31).contains($0) }) ?? true,
                  scrollDeltaX == nil,
                  scrollDeltaY == nil,
                  placeholder == nil else {
                throw ConversationModuleError.invalidEvent
            }
        case .navigationKey:
            guard navigationKey != nil,
                  pointerPhase == nil,
                  normalizedX == nil,
                  normalizedY == nil,
                  keyPhase == nil,
                  keyCode == nil,
                  buttonNumber == nil,
                  scrollDeltaX == nil,
                  scrollDeltaY == nil,
                  placeholder == nil else {
                throw ConversationModuleError.invalidEvent
            }
        case .rawKeyboard:
            guard keyPhase != nil,
                  let keyCode,
                  (0...255).contains(keyCode),
                  modifierFlags != nil,
                  pointerPhase == nil,
                  normalizedX == nil,
                  normalizedY == nil,
                  navigationKey == nil,
                  buttonNumber == nil,
                  scrollDeltaX == nil,
                  scrollDeltaY == nil,
                  placeholder == nil else {
                throw ConversationModuleError.invalidEvent
            }
        case .scroll:
            guard pointerPhase == nil,
                  let normalizedX,
                  let normalizedY,
                  normalizedX.isFinite,
                  normalizedY.isFinite,
                  (0...1).contains(normalizedX),
                  (0...1).contains(normalizedY),
                  let scrollDeltaX,
                  let scrollDeltaY,
                  scrollDeltaX.isFinite,
                  scrollDeltaY.isFinite,
                  abs(scrollDeltaX) <= 10_000,
                  abs(scrollDeltaY) <= 10_000,
                  navigationKey == nil,
                  keyPhase == nil,
                  keyCode == nil,
                  buttonNumber == nil,
                  placeholder == nil else {
                throw ConversationModuleError.invalidEvent
            }
        case .placeholder:
            guard placeholder != nil,
                  pointerPhase == nil,
                  normalizedX == nil,
                  normalizedY == nil,
                  navigationKey == nil,
                  keyPhase == nil,
                  keyCode == nil,
                  buttonNumber == nil,
                  scrollDeltaX == nil,
                  scrollDeltaY == nil else {
                throw ConversationModuleError.invalidEvent
            }
        }
        if let elapsedMilliseconds {
            guard (0...86_400_000).contains(elapsedMilliseconds) else {
                throw ConversationModuleError.invalidEvent
            }
        }
    }
}

struct ConversationModuleWindowContext: Codable, Equatable, Sendable {
    let bindingID: String
    let width: Int
    let height: Int

    func validate(allowedBindingIDs: [String]) throws {
        guard allowedBindingIDs.contains(bindingID),
              (100...8_192).contains(width),
              (100...8_192).contains(height) else {
            throw ConversationModuleError.windowBindingRejected
        }
    }
}

struct ConversationModuleRequest: Codable, Equatable, Sendable {
    let contractVersion: String
    let kind: ConversationModuleRequestKind
    let moduleID: String
    let requestID: String
    let turnID: String
    let sequence: Int
    let floor: ConversationFloorGrant
    let transcriptProvider: ConversationTranscriptProvider
    let narration: String
    let context: ConversationModuleContext
    let events: [ConversationModuleEvent]
    let window: ConversationModuleWindowContext?
    let provenance: ConversationModuleProvenance

    func validate(for manifest: ConversationModuleManifest) throws {
        try manifest.validate()
        guard contractVersion == manifest.contractVersion,
              moduleID == manifest.moduleID,
              requestID.range(
                  of: #"^request_[a-f0-9-]{36}$"#,
                  options: .regularExpression
              ) != nil,
              turnID.range(
                  of: #"^turn_[a-f0-9-]{36}$"#,
                  options: .regularExpression
              ) != nil,
              sequence >= 1,
              events.count <= ConversationModuleContract.maximumEvents else {
            throw ConversationModuleError.invalidRequest
        }

        let expectedFloorState: ConversationFloorState =
            kind == .turn ? .granted : .revoked
        try floor.validate(
            expectedModuleID: moduleID,
            expectedState: expectedFloorState
        )
        try provenance.validate(expectedSourceID: manifest.provenanceSourceID)
        try context.validate()

        switch kind {
        case .turn:
            let trimmed = narration.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty,
                  trimmed.count <= ConversationModuleContract.maximumNarrationCharacters,
                  manifest.allowedTranscriptProviders.contains(transcriptProvider),
                  manifest.capabilities.contains(.narration) else {
                if !manifest.allowedTranscriptProviders.contains(transcriptProvider) {
                    throw ConversationModuleError.transcriptProviderRejected
                }
                throw ConversationModuleError.narrationRejected
            }
        case .revoke, .end:
            guard narration.isEmpty, context.turns.isEmpty, events.isEmpty, window == nil else {
                throw ConversationModuleError.invalidRequest
            }
        }

        for (index, event) in events.enumerated() {
            try event.validate()
            guard event.sequence == index + 1 else {
                throw ConversationModuleError.sequenceMismatch
            }
            switch event.kind {
            case .normalizedPointer:
                guard manifest.capabilities.contains(.normalizedPointerEvents) else {
                    throw ConversationModuleError.capabilityRejected
                }
            case .navigationKey:
                guard manifest.capabilities.contains(.navigationKeys) else {
                    throw ConversationModuleError.capabilityRejected
                }
            case .rawKeyboard:
                guard manifest.capabilities.contains(.rawKeyboardEvents) else {
                    throw ConversationModuleError.capabilityRejected
                }
            case .scroll:
                guard manifest.capabilities.contains(.scrollEvents) else {
                    throw ConversationModuleError.capabilityRejected
                }
            case .placeholder:
                guard manifest.capabilities.contains(.placeholderEvents) else {
                    throw ConversationModuleError.capabilityRejected
                }
            }
        }

        if let window {
            guard manifest.capabilities.contains(.neutralWindowContext) else {
                throw ConversationModuleError.capabilityRejected
            }
            try window.validate(allowedBindingIDs: manifest.allowedWindowBindingIDs)
        }
    }
}

enum ConversationModuleState: String, Codable, Sendable {
    case idle
    case observing
    case checkpointReady = "checkpoint-ready"
    case awaitingAnswer = "awaiting-answer"
    case completed
    case refused
}

enum ConversationModuleStatusKind: String, Codable, Sendable {
    case info
    case attention
    case error
}

struct ConversationModuleStatus: Codable, Equatable, Sendable {
    let code: String
    let kind: ConversationModuleStatusKind
    let summary: String

    func validate() throws {
        guard ConversationModuleManifest.validIdentifier(code, maximum: 64),
              !summary.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              summary.count <= 240 else {
            throw ConversationModuleError.invalidResponse
        }
    }
}

struct ConversationModuleCheckpoint: Codable, Equatable, Sendable {
    let checkpointID: String
    let summary: String
    let confidence: Double

    func validate() throws {
        guard checkpointID.range(
            of: #"^checkpoint_[a-z0-9-]{1,64}$"#,
            options: .regularExpression
        ) != nil,
              !summary.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              summary.count <= 400,
              (0...1).contains(confidence) else {
            throw ConversationModuleError.invalidResponse
        }
    }
}

enum ConversationModuleActionKind: String, Codable, Sendable {
    case acknowledgeCheckpoint = "acknowledge-checkpoint"
    case discardCheckpoint = "discard-checkpoint"
    case reviewReplayProposal = "review-replay-proposal"
    case endModule = "end-module"
}

struct ConversationModuleProposedAction: Codable, Equatable, Sendable {
    let actionID: String
    let kind: ConversationModuleActionKind
    let title: String
    let humanApprovalRequired: Bool

    func validate() throws {
        guard actionID.range(
            of: #"^action_[a-z0-9-]{1,64}$"#,
            options: .regularExpression
        ) != nil,
              !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              title.count <= 120,
              humanApprovalRequired else {
            throw ConversationModuleError.invalidResponse
        }
    }
}

struct ConversationModuleResponse: Codable, Equatable, Sendable {
    let contractVersion: String
    let moduleID: String
    let requestID: String
    let turnID: String
    let sequence: Int
    let floor: ConversationFloorGrant
    let state: ConversationModuleState
    let reply: String?
    let statuses: [ConversationModuleStatus]
    let checkpoints: [ConversationModuleCheckpoint]
    let question: String?
    let proposedActions: [ConversationModuleProposedAction]
    let provenance: ConversationModuleProvenance

    func validate(
        for request: ConversationModuleRequest,
        manifest: ConversationModuleManifest,
        pinnedProvenance: ConversationModuleProvenance
    ) throws {
        guard contractVersion == request.contractVersion,
              moduleID == request.moduleID,
              requestID == request.requestID,
              turnID == request.turnID,
              sequence == request.sequence,
              floor == request.floor,
              provenance == pinnedProvenance,
              statuses.count <= ConversationModuleContract.maximumStatuses,
              checkpoints.count <= ConversationModuleContract.maximumCheckpoints,
              proposedActions.count
                <= ConversationModuleContract.maximumProposedActions else {
            throw ConversationModuleError.invalidResponse
        }
        try provenance.validate(expectedSourceID: manifest.provenanceSourceID)
        if let reply {
            guard !reply.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  reply.count <= ConversationModuleContract.maximumReplyCharacters else {
                throw ConversationModuleError.invalidResponse
            }
        }
        if let question {
            guard !question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  question.count
                    <= ConversationModuleContract.maximumQuestionCharacters else {
                throw ConversationModuleError.invalidResponse
            }
        }
        try statuses.forEach { try $0.validate() }
        try checkpoints.forEach { try $0.validate() }
        try proposedActions.forEach { try $0.validate() }

        guard checkpoints.isEmpty || manifest.capabilities.contains(.checkpoints),
              proposedActions.isEmpty
                || manifest.capabilities.contains(.proposedActions) else {
            throw ConversationModuleError.capabilityRejected
        }
    }
}

enum ConversationModuleError: LocalizedError, Equatable {
    case unsupportedContract
    case invalidManifest
    case privacyContractRejected
    case provenanceMismatch
    case healthMismatch
    case moduleUnavailable
    case floorAlreadyGranted
    case floorMissing
    case floorMismatch
    case invalidRequest
    case narrationRejected
    case transcriptProviderRejected
    case contextTooLarge
    case invalidEvent
    case sequenceMismatch
    case capabilityRejected
    case windowBindingRejected
    case invalidResponse
    case moduleRefused
    case responseTooLarge
    case rejected(Int)

    var errorDescription: String? {
        switch self {
        case .unsupportedContract:
            "The conversation module uses an unsupported contract version."
        case .invalidManifest:
            "The conversation module manifest is invalid."
        case .privacyContractRejected:
            "The conversation module requested a forbidden capability."
        case .provenanceMismatch:
            "The conversation module provenance changed or was not reported."
        case .healthMismatch:
            "The conversation module health response did not match its allowlist entry."
        case .moduleUnavailable:
            "The selected conversation module is unavailable."
        case .floorAlreadyGranted:
            "Return to the dashboard before giving another module the floor."
        case .floorMissing:
            "No conversation module currently has the floor."
        case .floorMismatch:
            "The conversation module floor token did not match."
        case .invalidRequest:
            "The conversation module request was invalid."
        case .narrationRejected:
            "The narration was empty, oversized, or unsupported."
        case .transcriptProviderRejected:
            "The transcription provider was missing or not allowlisted for this module."
        case .contextTooLarge:
            "The bounded conversation context was invalid."
        case .invalidEvent:
            "A normalized module event was invalid."
        case .sequenceMismatch:
            "The conversation module sequence was missing, replayed, or out of order."
        case .capabilityRejected:
            "The conversation module used a capability outside its allowlist."
        case .windowBindingRejected:
            "The neutral window binding was not allowlisted."
        case .invalidResponse:
            "The conversation module returned an invalid response."
        case .moduleRefused:
            "The conversation module refused the turn and returned control to the dashboard."
        case .responseTooLarge:
            "The conversation module response exceeded its safety limit."
        case let .rejected(status):
            "The conversation module declined the request (HTTP \(status))."
        }
    }
}

enum ConversationModuleCodec {
    static func encodeRequest(_ request: ConversationModuleRequest) throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return try encoder.encode(request)
    }

    static func decodeHealth(_ data: Data) throws -> ConversationModuleHealth {
        guard data.count <= ConversationModuleContract.maximumHealthBytes else {
            throw ConversationModuleError.responseTooLarge
        }
        let value = try JSONSerialization.jsonObject(with: data)
        let object = try strictObject(
            value,
            required: [
                "contractVersion", "moduleID", "state", "privacy", "provenance",
            ]
        )
        _ = try strictObject(
            object["privacy"],
            required: privacyKeys
        )
        _ = try strictObject(
            object["provenance"],
            required: ["sourceID", "buildDigest"]
        )
        return try JSONDecoder().decode(ConversationModuleHealth.self, from: data)
    }

    static func decodeResponse(_ data: Data) throws -> ConversationModuleResponse {
        guard data.count <= ConversationModuleContract.maximumResponseBytes else {
            throw ConversationModuleError.responseTooLarge
        }
        let value = try JSONSerialization.jsonObject(with: data)
        let object = try strictObject(
            value,
            required: [
                "contractVersion", "moduleID", "requestID", "turnID", "sequence",
                "floor", "state", "statuses", "checkpoints", "proposedActions",
                "provenance",
            ],
            optional: ["reply", "question"]
        )
        _ = try strictObject(
            object["floor"],
            required: ["state", "moduleID", "token"]
        )
        _ = try strictObject(
            object["provenance"],
            required: ["sourceID", "buildDigest"]
        )
        try strictArray(
            object["statuses"],
            required: ["code", "kind", "summary"]
        )
        try strictArray(
            object["checkpoints"],
            required: ["checkpointID", "summary", "confidence"]
        )
        try strictArray(
            object["proposedActions"],
            required: ["actionID", "kind", "title", "humanApprovalRequired"]
        )
        if let reply = object["reply"], !(reply is String) {
            throw ConversationModuleError.invalidResponse
        }
        if let question = object["question"], !(question is String) {
            throw ConversationModuleError.invalidResponse
        }
        return try JSONDecoder().decode(ConversationModuleResponse.self, from: data)
    }

    private static let privacyKeys: Set<String> = [
        "ephemeralOnly", "moduleOwnsMicrophone", "moduleOwnsUI", "moduleOwnsTTS",
        "arbitraryNetwork", "persistence", "screenCapture", "inputInjection",
        "executableReplay",
    ]

    private static func strictObject(
        _ value: Any?,
        required: Set<String>,
        optional: Set<String> = []
    ) throws -> [String: Any] {
        guard let object = value as? [String: Any],
              Set(object.keys) == required.union(optional).intersection(Set(object.keys)),
              required.isSubset(of: Set(object.keys)) else {
            throw ConversationModuleError.invalidResponse
        }
        return object
    }

    private static func strictArray(
        _ value: Any?,
        required: Set<String>
    ) throws {
        guard let values = value as? [Any] else {
            throw ConversationModuleError.invalidResponse
        }
        for value in values {
            _ = try strictObject(value, required: required)
        }
    }
}

protocol ConversationModuleTransport: Sendable {
    func health(for manifest: ConversationModuleManifest) async throws
        -> ConversationModuleHealth
    func perform(
        _ request: ConversationModuleRequest,
        manifest: ConversationModuleManifest
    ) async throws -> ConversationModuleResponse
}

struct ConversationModuleRegistration: Sendable {
    let manifest: ConversationModuleManifest
    let transport: any ConversationModuleTransport
}

enum ConversationModuleAllowlist {
    static let syntheticManifest = ConversationModuleManifest(
        contractVersion: ConversationModuleContract.version,
        moduleID: "firestarter.synthetic.checkpoint",
        displayName: "Synthetic checkpoint reference",
        capabilities: [.narration, .checkpoints, .proposedActions],
        privacy: .hostControlled,
        provenanceSourceID: "firestarter.operations-floater.synthetic",
        allowedTranscriptProviders: [.typedKeyboard, .onDevice, .syntheticFixture],
        allowedWindowBindingIDs: []
    )

    static let geometryRecorderManifest = ConversationModuleManifest(
        contractVersion: ConversationModuleContract.version,
        moduleID: "auggie.verbal-orders.synthetic-geometry-recorder",
        displayName: "Synthetic geometry recorder",
        capabilities: [
            .narration,
            .normalizedPointerEvents,
            .navigationKeys,
            .placeholderEvents,
            .neutralWindowContext,
            .checkpoints,
            .proposedActions,
        ],
        privacy: .hostControlled,
        provenanceSourceID: "auggie.project-verbal-orders.geometry-recorder",
        allowedTranscriptProviders: [.onDevice, .syntheticFixture],
        allowedWindowBindingIDs: [
            "verbal-orders.synthetic.geometry-canvas",
        ]
    )

    static let relativeXYRecorderManifest = ConversationModuleManifest(
        contractVersion: ConversationModuleContract.version,
        moduleID: "auggie.verbal-orders.relative-xy-recorder",
        displayName: "Relative XY recorder",
        capabilities: [
            .narration,
            .normalizedPointerEvents,
            .navigationKeys,
            .rawKeyboardEvents,
            .scrollEvents,
            .neutralWindowContext,
            .checkpoints,
            .proposedActions,
        ],
        privacy: .hostControlled,
        provenanceSourceID: "auggie.project-verbal-orders.relative-xy-recorder",
        allowedTranscriptProviders: [.onDevice, .syntheticFixture],
        allowedWindowBindingIDs: [
            "verbal-orders.neutral.selected-window",
        ]
    )

    static func liveRegistrations() -> [ConversationModuleRegistration] {
        [
            ConversationModuleRegistration(
                manifest: syntheticManifest,
                transport: SyntheticConversationModule()
            ),
            ConversationModuleRegistration(
                manifest: geometryRecorderManifest,
                transport: LoopbackConversationModuleClient()
            ),
            ConversationModuleRegistration(
                manifest: relativeXYRecorderManifest,
                transport: LoopbackConversationModuleClient()
            ),
        ]
    }
}

actor SyntheticConversationModule: ConversationModuleTransport {
    private static let provenance = ConversationModuleProvenance(
        sourceID: "firestarter.operations-floater.synthetic",
        buildDigest: "7e3b6a1b0d4586f3d3b99a8e4b5114ca4f963f1b6ce974cf81682433c73547de"
    )

    private var activeToken: String?
    private var nextSequence = 1
    private var checkpointCount = 0

    func health(for manifest: ConversationModuleManifest) async throws
        -> ConversationModuleHealth {
        let health = ConversationModuleHealth(
            contractVersion: ConversationModuleContract.version,
            moduleID: manifest.moduleID,
            state: .ready,
            privacy: .hostControlled,
            provenance: Self.provenance
        )
        try health.validate(for: manifest)
        return health
    }

    func perform(
        _ request: ConversationModuleRequest,
        manifest: ConversationModuleManifest
    ) async throws -> ConversationModuleResponse {
        let snapshot = (activeToken, nextSequence, checkpointCount)
        do {
            try request.validate(for: manifest)
            guard request.provenance == Self.provenance else {
                throw ConversationModuleError.provenanceMismatch
            }
            if let activeToken {
                guard activeToken == request.floor.token else {
                    throw ConversationModuleError.floorMismatch
                }
            } else {
                activeToken = request.floor.token
            }
            guard request.sequence == nextSequence else {
                throw ConversationModuleError.sequenceMismatch
            }

            let response: ConversationModuleResponse
            switch request.kind {
            case .turn:
                checkpointCount += 1
                response = ConversationModuleResponse(
                    contractVersion: request.contractVersion,
                    moduleID: request.moduleID,
                    requestID: request.requestID,
                    turnID: request.turnID,
                    sequence: request.sequence,
                    floor: request.floor,
                    state: .checkpointReady,
                    reply: "Synthetic checkpoint \(checkpointCount) is ready for review.",
                    statuses: [
                        ConversationModuleStatus(
                            code: "checkpoint-ready",
                            kind: .info,
                            summary: "A bounded synthetic narration turn was accepted."
                        ),
                    ],
                    checkpoints: [
                        ConversationModuleCheckpoint(
                            checkpointID: "checkpoint_\(checkpointCount)",
                            summary: "Synthetic checkpoint with no captured content.",
                            confidence: 1
                        ),
                    ],
                    question: nil,
                    proposedActions: [
                        ConversationModuleProposedAction(
                            actionID: "action_review-\(checkpointCount)",
                            kind: .acknowledgeCheckpoint,
                            title: "Review synthetic checkpoint",
                            humanApprovalRequired: true
                        ),
                    ],
                    provenance: Self.provenance
                )
            case .revoke, .end:
                response = ConversationModuleResponse(
                    contractVersion: request.contractVersion,
                    moduleID: request.moduleID,
                    requestID: request.requestID,
                    turnID: request.turnID,
                    sequence: request.sequence,
                    floor: request.floor,
                    state: .idle,
                    reply: nil,
                    statuses: [],
                    checkpoints: [],
                    question: nil,
                    proposedActions: [],
                    provenance: Self.provenance
                )
            }
            try response.validate(
                for: request,
                manifest: manifest,
                pinnedProvenance: Self.provenance
            )
            nextSequence += 1
            if request.kind != .turn {
                activeToken = nil
                nextSequence = 1
                checkpointCount = 0
            }
            return response
        } catch {
            activeToken = snapshot.0
            nextSequence = snapshot.1
            checkpointCount = snapshot.2
            throw error
        }
    }
}

struct LoopbackConversationModuleClient: ConversationModuleTransport {
    private final class NoRedirectDelegate: NSObject, URLSessionTaskDelegate,
        @unchecked Sendable {
        func urlSession(
            _ session: URLSession,
            task: URLSessionTask,
            willPerformHTTPRedirection response: HTTPURLResponse,
            newRequest request: URLRequest,
            completionHandler: @escaping (URLRequest?) -> Void
        ) {
            completionHandler(nil)
        }
    }

    private let session: URLSession

    init(session: URLSession? = nil) {
        self.session = session ?? Self.makeSession()
    }

    func health(for manifest: ConversationModuleManifest) async throws
        -> ConversationModuleHealth {
        var request = URLRequest(url: endpoint(for: manifest, action: "health"))
        request.httpMethod = "GET"
        request.timeoutInterval = 2
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue(
            ConversationModuleContract.clientIdentifier,
            forHTTPHeaderField: "X-Client-App"
        )
        let (data, response) = try await session.data(for: request)
        try validateHTTP(response)
        let health = try ConversationModuleCodec.decodeHealth(data)
        try health.validate(for: manifest)
        return health
    }

    func perform(
        _ requestValue: ConversationModuleRequest,
        manifest: ConversationModuleManifest
    ) async throws -> ConversationModuleResponse {
        try requestValue.validate(for: manifest)
        var request = URLRequest(url: endpoint(for: manifest, action: "turn"))
        request.httpMethod = "POST"
        request.timeoutInterval = 10
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(
            ConversationModuleContract.clientIdentifier,
            forHTTPHeaderField: "X-Client-App"
        )
        request.httpBody = try ConversationModuleCodec.encodeRequest(requestValue)
        let (data, response) = try await session.data(for: request)
        try validateHTTP(response)
        return try ConversationModuleCodec.decodeResponse(data)
    }

    private func endpoint(
        for manifest: ConversationModuleManifest,
        action: String
    ) -> URL {
        ConversationModuleContract.loopbackBaseURL
            .appendingPathComponent(manifest.moduleID, isDirectory: true)
            .appendingPathComponent(action)
    }

    private func validateHTTP(_ response: URLResponse) throws {
        guard let response = response as? HTTPURLResponse else {
            throw ConversationModuleError.invalidResponse
        }
        guard (200..<300).contains(response.statusCode) else {
            throw ConversationModuleError.rejected(response.statusCode)
        }
    }

    private static func makeSession() -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.urlCache = nil
        configuration.httpCookieStorage = nil
        configuration.urlCredentialStorage = nil
        configuration.httpShouldSetCookies = false
        return URLSession(
            configuration: configuration,
            delegate: NoRedirectDelegate(),
            delegateQueue: nil
        )
    }
}

@MainActor
final class ConversationModuleHostSession: ObservableObject {
    @Published private(set) var manifests: [ConversationModuleManifest]
    @Published var selectedModuleID: String?
    @Published private(set) var healthByModuleID: [String: ConversationModuleHealth] = [:]
    @Published private(set) var activeFloor: ConversationFloorGrant?
    @Published private(set) var activeState: ConversationModuleState = .idle
    @Published private(set) var lastResponse: ConversationModuleResponse?
    @Published private(set) var lastError: String?
    @Published private(set) var isWorking = false

    private let registrations: [String: ConversationModuleRegistration]
    private let tokenFactory: () -> String
    private var pinnedProvenance: ConversationModuleProvenance?
    private var nextSequence = 1

    init(
        registrations: [ConversationModuleRegistration] =
            ConversationModuleAllowlist.liveRegistrations(),
        tokenFactory: @escaping () -> String = {
            "floor_\(UUID().uuidString.lowercased())"
        }
    ) {
        let sortedManifests = registrations.map(\.manifest).sorted {
            $0.displayName < $1.displayName
        }
        self.registrations = Dictionary(
            uniqueKeysWithValues: registrations.map { ($0.manifest.moduleID, $0) }
        )
        self.tokenFactory = tokenFactory
        manifests = sortedManifests
        selectedModuleID = sortedManifests.first?.moduleID
    }

    var activeManifest: ConversationModuleManifest? {
        guard let moduleID = activeFloor?.moduleID else { return nil }
        return registrations[moduleID]?.manifest
    }

    func refreshHealth(moduleID: String) async {
        guard let registration = registrations[moduleID] else { return }
        do {
            let health = try await registration.transport.health(
                for: registration.manifest
            )
            try health.validate(for: registration.manifest)
            healthByModuleID[moduleID] = health
        } catch {
            healthByModuleID[moduleID] = nil
        }
    }

    func grantSelectedFloor() async {
        do {
            guard activeFloor == nil else {
                throw ConversationModuleError.floorAlreadyGranted
            }
            guard let moduleID = selectedModuleID,
                  let registration = registrations[moduleID] else {
                throw ConversationModuleError.moduleUnavailable
            }
            isWorking = true
            defer { isWorking = false }
            let health = try await registration.transport.health(
                for: registration.manifest
            )
            try health.validate(for: registration.manifest)
            guard health.state == .ready else {
                throw ConversationModuleError.moduleUnavailable
            }
            let floor = ConversationFloorGrant(
                state: .granted,
                moduleID: moduleID,
                token: tokenFactory()
            )
            try floor.validate(expectedModuleID: moduleID, expectedState: .granted)
            healthByModuleID[moduleID] = health
            pinnedProvenance = health.provenance
            activeFloor = floor
            activeState = .idle
            lastResponse = nil
            lastError = nil
            nextSequence = 1
        } catch {
            lastError = error.localizedDescription
        }
    }

    func submit(
        narration: String,
        transcriptProvider: ConversationTranscriptProvider,
        context: ConversationModuleContext,
        events: [ConversationModuleEvent] = [],
        window: ConversationModuleWindowContext? = nil
    ) async throws -> ConversationModuleResponse {
        guard let floor = activeFloor,
              let provenance = pinnedProvenance,
              let registration = registrations[floor.moduleID] else {
            throw ConversationModuleError.floorMissing
        }
        guard narration.count <= ConversationModuleContract.maximumNarrationCharacters else {
            throw ConversationModuleError.narrationRejected
        }
        isWorking = true
        defer { isWorking = false }
        let request = ConversationModuleRequest(
            contractVersion: ConversationModuleContract.version,
            kind: .turn,
            moduleID: floor.moduleID,
            requestID: "request_\(UUID().uuidString.lowercased())",
            turnID: "turn_\(UUID().uuidString.lowercased())",
            sequence: nextSequence,
            floor: floor,
            transcriptProvider: transcriptProvider,
            narration: narration,
            context: context,
            events: events,
            window: window,
            provenance: provenance
        )
        try request.validate(for: registration.manifest)
        do {
            let response = try await registration.transport.perform(
                request,
                manifest: registration.manifest
            )
            try response.validate(
                for: request,
                manifest: registration.manifest,
                pinnedProvenance: provenance
            )
            guard response.state != .refused else {
                throw ConversationModuleError.moduleRefused
            }
            lastResponse = response
            activeState = response.state
            lastError = nil
            nextSequence += 1
            return response
        } catch {
            let description = error.localizedDescription
            await closeFloor(kind: .revoke)
            lastError = description
            throw error
        }
    }

    func revokeFloor() async {
        await closeFloor(kind: .revoke)
    }

    func endFloor() async {
        await closeFloor(kind: .end)
    }

    private func closeFloor(kind: ConversationModuleRequestKind) async {
        guard let grantedFloor = activeFloor,
              let provenance = pinnedProvenance,
              let registration = registrations[grantedFloor.moduleID] else {
            clearFloor()
            return
        }
        let revokedFloor = ConversationFloorGrant(
            state: .revoked,
            moduleID: grantedFloor.moduleID,
            token: grantedFloor.token
        )
        let request = ConversationModuleRequest(
            contractVersion: ConversationModuleContract.version,
            kind: kind,
            moduleID: grantedFloor.moduleID,
            requestID: "request_\(UUID().uuidString.lowercased())",
            turnID: "turn_\(UUID().uuidString.lowercased())",
            sequence: nextSequence,
            floor: revokedFloor,
            transcriptProvider: .typedKeyboard,
            narration: "",
            context: .empty,
            events: [],
            window: nil,
            provenance: provenance
        )
        do {
            try request.validate(for: registration.manifest)
            let response = try await registration.transport.perform(
                request,
                manifest: registration.manifest
            )
            try response.validate(
                for: request,
                manifest: registration.manifest,
                pinnedProvenance: provenance
            )
        } catch {
            // Revocation is fail-closed locally even when the module is gone.
        }
        clearFloor()
    }

    private func clearFloor() {
        activeFloor = nil
        activeState = .idle
        pinnedProvenance = nil
        nextSequence = 1
        lastResponse = nil
        lastError = nil
        isWorking = false
    }
}
