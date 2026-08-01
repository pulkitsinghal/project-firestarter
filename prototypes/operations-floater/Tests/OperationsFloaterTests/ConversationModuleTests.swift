import Foundation
import Testing
@testable import OperationsFloater

@Suite("Conversation module contract")
struct ConversationModuleTests {
    private let floor = ConversationFloorGrant(
        state: .granted,
        moduleID: ConversationModuleAllowlist.syntheticManifest.moduleID,
        token: "floor_00000000-0000-0000-0000-000000000001"
    )
    private let provenance = ConversationModuleProvenance(
        sourceID: "firestarter.operations-floater.synthetic",
        buildDigest: "7e3b6a1b0d4586f3d3b99a8e4b5114ca4f963f1b6ce974cf81682433c73547de"
    )
    /// A neutral, host-controlled test manifest that exercises the generic
    /// conversation-module contract (pointer, key, scroll, placeholder, and
    /// window events) without referencing any product-specific module.
    private let neutralInputManifest = ConversationModuleManifest(
        contractVersion: ConversationModuleContract.version,
        moduleID: "firestarter.test.neutral-input",
        displayName: "Neutral input contract fixture",
        capabilities: [
            .narration,
            .normalizedPointerEvents,
            .navigationKeys,
            .rawKeyboardEvents,
            .scrollEvents,
            .placeholderEvents,
            .neutralWindowContext,
            .checkpoints,
            .proposedActions,
        ],
        privacy: .hostControlled,
        provenanceSourceID: "firestarter.test.neutral-input",
        allowedTranscriptProviders: [.onDevice, .syntheticFixture],
        allowedWindowBindingIDs: ["firestarter.test.neutral-window"]
    )

    @Test("The static allowlist accepts only host-controlled privacy")
    func allowlistPrivacy() throws {
        try ConversationModuleAllowlist.syntheticManifest.validate()

        for manifest in [
            ConversationModuleAllowlist.syntheticManifest,
        ] {
            #expect(manifest.privacy == .hostControlled)
            #expect(manifest.privacy.ephemeralOnly)
            #expect(!manifest.privacy.moduleOwnsMicrophone)
            #expect(!manifest.privacy.moduleOwnsUI)
            #expect(!manifest.privacy.moduleOwnsTTS)
            #expect(!manifest.privacy.arbitraryNetwork)
            #expect(!manifest.privacy.persistence)
            #expect(!manifest.privacy.screenCapture)
            #expect(!manifest.privacy.inputInjection)
            #expect(!manifest.privacy.executableReplay)
        }
    }

    @Test("The contract accepts the neutral window binding and the bounded input vocabulary")
    func neutralInputVocabulary() throws {
        let manifest = neutralInputManifest
        #expect(
            manifest.allowedWindowBindingIDs
                == ["firestarter.test.neutral-window"]
        )
        #expect(manifest.capabilities.contains(.rawKeyboardEvents))
        #expect(manifest.capabilities.contains(.scrollEvents))

        let events = [
            ConversationModuleEvent(
                eventID: "event_pointer-1",
                sequence: 1,
                kind: .normalizedPointer,
                pointerPhase: .drag,
                normalizedX: 0.45,
                normalizedY: 0.55,
                buttonNumber: 0,
                elapsedMilliseconds: 100
            ),
            ConversationModuleEvent(
                eventID: "event_key-2",
                sequence: 2,
                kind: .rawKeyboard,
                keyPhase: .down,
                keyCode: 12,
                modifierFlags: 1 << 17,
                elapsedMilliseconds: 110
            ),
            ConversationModuleEvent(
                eventID: "event_scroll-3",
                sequence: 3,
                kind: .scroll,
                normalizedX: 0.45,
                normalizedY: 0.55,
                scrollDeltaX: 0,
                scrollDeltaY: -4,
                elapsedMilliseconds: 120
            ),
        ]
        let value = request(
            manifest: manifest,
            floor: ConversationFloorGrant(
                state: .granted,
                moduleID: manifest.moduleID,
                token: floor.token
            ),
            provenance: ConversationModuleProvenance(
                sourceID: manifest.provenanceSourceID,
                buildDigest: provenance.buildDigest
            ),
            events: events,
            window: ConversationModuleWindowContext(
                bindingID: "firestarter.test.neutral-window",
                width: 1_437,
                height: 913
            )
        )

        try value.validate(for: manifest)
    }

    @Test("A module cannot request microphone, UI, network, persistence, capture, or replay")
    func forbiddenPrivacyCapabilityFailsClosed() {
        let rejected = ConversationModuleManifest(
            contractVersion: ConversationModuleContract.version,
            moduleID: "firestarter.synthetic.rejected",
            displayName: "Rejected synthetic module",
            capabilities: [.narration],
            privacy: ConversationModulePrivacy(
                ephemeralOnly: true,
                moduleOwnsMicrophone: true,
                moduleOwnsUI: false,
                moduleOwnsTTS: false,
                arbitraryNetwork: false,
                persistence: false,
                screenCapture: false,
                inputInjection: false,
                executableReplay: false
            ),
            provenanceSourceID: "firestarter.synthetic.rejected",
            allowedTranscriptProviders: [.syntheticFixture],
            allowedWindowBindingIDs: []
        )

        #expect(throws: ConversationModuleError.privacyContractRejected) {
            try rejected.validate()
        }
    }

    @Test("Pointer and window context are bounded and capability-gated")
    func boundedEventsAndWindow() throws {
        let event = ConversationModuleEvent(
            eventID: "event_pointer-1",
            sequence: 1,
            kind: .normalizedPointer,
            pointerPhase: .move,
            normalizedX: 0.25,
            normalizedY: 0.75,
            navigationKey: nil,
            placeholder: nil
        )
        let manifest = neutralInputManifest
        let validRequest = request(
            manifest: manifest,
            floor: ConversationFloorGrant(
                state: .granted,
                moduleID: manifest.moduleID,
                token: floor.token
            ),
            provenance: ConversationModuleProvenance(
                sourceID: manifest.provenanceSourceID,
                buildDigest: provenance.buildDigest
            ),
            events: [event],
            window: ConversationModuleWindowContext(
                bindingID: "firestarter.test.neutral-window",
                width: 1280,
                height: 720
            )
        )

        try validRequest.validate(for: manifest)

        let drifted = request(
            manifest: manifest,
            floor: validRequest.floor,
            provenance: validRequest.provenance,
            events: [event],
            window: ConversationModuleWindowContext(
                bindingID: "private.unallowlisted.window",
                width: 1280,
                height: 720
            )
        )
        #expect(throws: ConversationModuleError.windowBindingRejected) {
            try drifted.validate(for: manifest)
        }
    }

    @Test("Event sequences are contiguous and Escape is reserved to the host")
    func eventSequenceAndEscapePolicy() {
        let keys = ConversationNavigationKey.allCasesForTests
        #expect(!keys.map(\.rawValue).contains("escape"))

        let event = ConversationModuleEvent(
            eventID: "event_key-2",
            sequence: 2,
            kind: .navigationKey,
            pointerPhase: nil,
            normalizedX: nil,
            normalizedY: nil,
            navigationKey: .tab,
            placeholder: nil
        )
        let manifest = neutralInputManifest
        let request = request(
            manifest: manifest,
            floor: ConversationFloorGrant(
                state: .granted,
                moduleID: manifest.moduleID,
                token: floor.token
            ),
            provenance: ConversationModuleProvenance(
                sourceID: manifest.provenanceSourceID,
                buildDigest: provenance.buildDigest
            ),
            events: [event]
        )

        #expect(throws: ConversationModuleError.sequenceMismatch) {
            try request.validate(for: manifest)
        }
    }

    @Test("Every proposed module action remains separately human-approved")
    func actionsRequireHumanApproval() {
        let action = ConversationModuleProposedAction(
            actionID: "action_replay-1",
            kind: .reviewReplayProposal,
            title: "Review replay proposal",
            humanApprovalRequired: false
        )

        #expect(throws: ConversationModuleError.invalidResponse) {
            try action.validate()
        }
    }

    @Test("Revoke and end control envelopes do not need a transcript provider")
    func controlEnvelopeProviderIsExempt() throws {
        let manifest = neutralInputManifest
        let controlRequest = ConversationModuleRequest(
            contractVersion: ConversationModuleContract.version,
            kind: .revoke,
            moduleID: manifest.moduleID,
            requestID: "request_00000000-0000-0000-0000-000000000010",
            turnID: "turn_00000000-0000-0000-0000-000000000010",
            sequence: 2,
            floor: ConversationFloorGrant(
                state: .revoked,
                moduleID: manifest.moduleID,
                token: floor.token
            ),
            transcriptProvider: .typedKeyboard,
            narration: "",
            context: .empty,
            events: [],
            window: nil,
            provenance: ConversationModuleProvenance(
                sourceID: manifest.provenanceSourceID,
                buildDigest: provenance.buildDigest
            )
        )

        try controlRequest.validate(for: manifest)
    }

    @Test("Unknown response and nested health fields fail closed")
    func strictUnknownFields() throws {
        let health = ConversationModuleHealth(
            contractVersion: ConversationModuleContract.version,
            moduleID: ConversationModuleAllowlist.syntheticManifest.moduleID,
            state: .ready,
            privacy: .hostControlled,
            provenance: provenance
        )
        let encoder = JSONEncoder()
        let healthObject = try #require(
            JSONSerialization.jsonObject(with: encoder.encode(health))
                as? [String: Any]
        )
        var healthWithUnknown = healthObject
        healthWithUnknown["endpoint"] = "https://not-allowed.example"
        let unknownHealthData = try JSONSerialization.data(
            withJSONObject: healthWithUnknown
        )
        #expect(throws: ConversationModuleError.invalidResponse) {
            _ = try ConversationModuleCodec.decodeHealth(unknownHealthData)
        }

        let validResponse = response(for: request())
        let responseObject = try #require(
            JSONSerialization.jsonObject(with: encoder.encode(validResponse))
                as? [String: Any]
        )
        var responseWithUnknown = responseObject
        responseWithUnknown["executableReplay"] = ["steps": ["click"]]
        let unknownResponseData = try JSONSerialization.data(
            withJSONObject: responseWithUnknown
        )
        #expect(throws: ConversationModuleError.invalidResponse) {
            _ = try ConversationModuleCodec.decodeResponse(unknownResponseData)
        }

        var nullQuestionResponse = responseObject
        nullQuestionResponse["question"] = NSNull()
        let nullQuestionData = try JSONSerialization.data(
            withJSONObject: nullQuestionResponse
        )
        #expect(throws: ConversationModuleError.invalidResponse) {
            _ = try ConversationModuleCodec.decodeResponse(nullQuestionData)
        }
    }

    @Test("A sequence gap refuses without advancing the synthetic module")
    func syntheticRollbackOnSequenceGap() async throws {
        let module = SyntheticConversationModule()
        let manifest = ConversationModuleAllowlist.syntheticManifest
        let first = request(sequence: 1)
        _ = try await module.perform(first, manifest: manifest)

        let gap = request(sequence: 3)
        await #expect(throws: ConversationModuleError.sequenceMismatch) {
            _ = try await module.perform(gap, manifest: manifest)
        }

        let second = request(sequence: 2)
        let response = try await module.perform(second, manifest: manifest)
        #expect(response.sequence == 2)
        #expect(response.state == .checkpointReady)
    }

    @Test("Revocation clears ephemeral state and a new floor starts at sequence one")
    @MainActor
    func hostFloorLifecycle() async throws {
        let host = ConversationModuleHostSession(
            registrations: [
                ConversationModuleRegistration(
                    manifest: ConversationModuleAllowlist.syntheticManifest,
                    transport: SyntheticConversationModule()
                ),
            ],
            tokenFactory: { floor.token }
        )

        await host.grantSelectedFloor()
        #expect(host.activeFloor == floor)
        let reply = try await host.submit(
            narration: "Synthetic narration",
            transcriptProvider: .syntheticFixture,
            context: .empty
        )
        #expect(reply.state == .checkpointReady)
        #expect(reply.checkpoints.count == 1)

        await host.revokeFloor()
        #expect(host.activeFloor == nil)
        #expect(host.activeState == .idle)
        #expect(host.lastResponse == nil)

        await host.grantSelectedFloor()
        let freshReply = try await host.submit(
            narration: "Fresh synthetic narration",
            transcriptProvider: .syntheticFixture,
            context: .empty
        )
        #expect(freshReply.sequence == 1)
        #expect(freshReply.checkpoints.first?.checkpointID == "checkpoint_1")
    }

    @Test("A refused response revokes the floor and restores dashboard control")
    @MainActor
    func refusedResponseRevokesFloor() async {
        let host = ConversationModuleHostSession(
            registrations: [
                ConversationModuleRegistration(
                    manifest: ConversationModuleAllowlist.syntheticManifest,
                    transport: RefusingConversationModule()
                ),
            ],
            tokenFactory: { floor.token }
        )

        await host.grantSelectedFloor()
        await #expect(throws: ConversationModuleError.moduleRefused) {
            _ = try await host.submit(
                narration: "Synthetic refusal",
                transcriptProvider: .syntheticFixture,
                context: .empty
            )
        }
        #expect(host.activeFloor == nil)
        #expect(host.activeState == .idle)
        #expect(host.lastResponse == nil)
    }

    private func request(
        manifest: ConversationModuleManifest =
            ConversationModuleAllowlist.syntheticManifest,
        floor: ConversationFloorGrant? = nil,
        provenance: ConversationModuleProvenance? = nil,
        sequence: Int = 1,
        events: [ConversationModuleEvent] = [],
        window: ConversationModuleWindowContext? = nil
    ) -> ConversationModuleRequest {
        ConversationModuleRequest(
            contractVersion: ConversationModuleContract.version,
            kind: .turn,
            moduleID: manifest.moduleID,
            requestID: "request_00000000-0000-0000-0000-000000000001",
            turnID: "turn_00000000-0000-0000-0000-000000000001",
            sequence: sequence,
            floor: floor ?? self.floor,
            transcriptProvider: .syntheticFixture,
            narration: "Synthetic narration",
            context: .empty,
            events: events,
            window: window,
            provenance: provenance ?? self.provenance
        )
    }

    private func response(
        for request: ConversationModuleRequest
    ) -> ConversationModuleResponse {
        ConversationModuleResponse(
            contractVersion: request.contractVersion,
            moduleID: request.moduleID,
            requestID: request.requestID,
            turnID: request.turnID,
            sequence: request.sequence,
            floor: request.floor,
            state: .checkpointReady,
            reply: "Synthetic reply",
            statuses: [],
            checkpoints: [],
            question: nil,
            proposedActions: [],
            provenance: request.provenance
        )
    }
}

private actor RefusingConversationModule: ConversationModuleTransport {
    private let provenance = ConversationModuleProvenance(
        sourceID: "firestarter.operations-floater.synthetic",
        buildDigest: "7e3b6a1b0d4586f3d3b99a8e4b5114ca4f963f1b6ce974cf81682433c73547de"
    )

    func health(
        for manifest: ConversationModuleManifest
    ) async throws -> ConversationModuleHealth {
        ConversationModuleHealth(
            contractVersion: manifest.contractVersion,
            moduleID: manifest.moduleID,
            state: .ready,
            privacy: manifest.privacy,
            provenance: provenance
        )
    }

    func perform(
        _ request: ConversationModuleRequest,
        manifest: ConversationModuleManifest
    ) async throws -> ConversationModuleResponse {
        ConversationModuleResponse(
            contractVersion: request.contractVersion,
            moduleID: request.moduleID,
            requestID: request.requestID,
            turnID: request.turnID,
            sequence: request.sequence,
            floor: request.floor,
            state: request.kind == .turn ? .refused : .idle,
            reply: request.kind == .turn ? "Synthetic refusal" : nil,
            statuses: [],
            checkpoints: [],
            question: nil,
            proposedActions: [],
            provenance: provenance
        )
    }
}

private extension ConversationNavigationKey {
    static var allCasesForTests: [ConversationNavigationKey] {
        [
            .tab, .returnKey, .space, .arrowLeft, .arrowRight, .arrowUp,
            .arrowDown, .delete,
        ]
    }
}
