import Foundation
import Testing
@testable import OperationsFloater

@Suite("Voice conversation lifecycle")
@MainActor
struct ConversationVoiceTests {
    @Test("Voice and spoken replies are explicitly off by default")
    func defaultsAreOff() {
        let engine = SyntheticTranscriptionEngine()
        let speech = SyntheticSpeechOutput()
        let session = VoiceConversationSession(engine: engine, speechOutput: speech)

        #expect(session.state == .off)
        #expect(!session.spokenRepliesEnabled)
        #expect(engine.startCount == 0)
        #expect(speech.spokenTexts.isEmpty)
    }

    @Test("Permission denial fails closed without starting audio")
    func permissionDenialFailsClosed() async {
        let engine = SyntheticTranscriptionEngine(authorization: .denied)
        let session = VoiceConversationSession(
            engine: engine,
            speechOutput: SyntheticSpeechOutput()
        )

        await session.start()

        #expect(session.state == .unavailable)
        #expect(engine.startCount == 0)
        #expect(session.lastError == ConversationVoiceError.permissionDenied.localizedDescription)
    }

    @Test("Missing or unallowlisted provider metadata fails closed")
    func providerMetadataFailsClosed() async {
        let engine = SyntheticTranscriptionEngine(provider: .typedKeyboard)
        let session = VoiceConversationSession(
            engine: engine,
            speechOutput: SyntheticSpeechOutput()
        )

        await session.start()

        #expect(session.state == .unavailable)
        #expect(engine.startCount == 0)
        #expect(
            session.lastError
                == ConversationVoiceError.providerMetadataUnavailable.localizedDescription
        )
    }

    @Test("Stopping while permission is pending cannot start the microphone later")
    func stopCancelsPendingPermissionStart() async {
        let engine = SuspendedAuthorizationEngine()
        let session = VoiceConversationSession(
            engine: engine,
            speechOutput: SyntheticSpeechOutput()
        )

        let startTask = Task {
            await session.start()
        }
        for _ in 0..<20 where !engine.isAwaitingAuthorization {
            await Task.yield()
        }
        #expect(engine.isAwaitingAuthorization)
        #expect(session.state == .requestingPermission)

        session.stop()
        engine.resolveAuthorization(.authorized)
        await startTask.value

        #expect(session.state == .off)
        #expect(engine.startCount == 0)
        #expect(!engine.isRunning)
    }

    @Test("A finalized transcript stages immediately and submits after exactly two seconds")
    func syntheticTranscriptLifecycle() async {
        let engine = SyntheticTranscriptionEngine()
        let sleeper = ControlledDebounceSleeper()
        let startedAt = Date(timeIntervalSince1970: 1_000)
        let session = VoiceConversationSession(
            engine: engine,
            speechOutput: SyntheticSpeechOutput(),
            debounceSleeper: { duration in
                try await sleeper.sleep(for: duration)
            },
            now: { startedAt }
        )
        var staged: [String] = []
        var submitted: (String, ConversationTranscriptProvider)?
        session.onTranscriptStaged = { staged.append($0) }
        session.onFinalTranscript = { text, provider in
            submitted = (text, provider)
        }

        await session.start()
        engine.emit(.success(ConversationTranscriptResult(
            text: "Synthetic narration",
            isFinal: true
        )))
        await waitForSleeper(sleeper, count: 1)

        #expect(staged == ["Synthetic narration"])
        #expect(session.state == .listening)
        #expect(session.hasPendingSubmission)
        #expect(
            session.pendingSubmissionWindow
                == VoiceSubmissionWindow(
                    startedAt: startedAt,
                    deadline: startedAt.addingTimeInterval(2)
                )
        )
        #expect(submitted == nil)
        #expect(await sleeper.requestedDurations() == [.seconds(2)])

        await sleeper.resumeNext()
        await settle()

        #expect(session.state == .thinking)
        #expect(submitted?.0 == "Synthetic narration")
        #expect(submitted?.1 == .syntheticFixture)
        #expect(!engine.isRunning)
        #expect(session.pendingSubmissionWindow == nil)

        session.handleReplyFailure()
        #expect(session.state == .listening)
        session.stop()
        #expect(session.state == .off)
        #expect(session.transcriptPreview.isEmpty)
    }

    @Test("Quiet-time progress is bounded before, during, and after two seconds")
    func quietTimeProgressIsBounded() {
        let startedAt = Date(timeIntervalSince1970: 2_000)
        let window = VoiceSubmissionWindow(
            startedAt: startedAt,
            deadline: startedAt.addingTimeInterval(2)
        )

        #expect(window.progress(at: startedAt.addingTimeInterval(-1)) == 0)
        #expect(window.progress(at: startedAt.addingTimeInterval(1)) == 0.5)
        #expect(window.progress(at: startedAt.addingTimeInterval(3)) == 1)
    }

    @Test("A stable partial transcript submits after exactly two seconds")
    func partialTranscriptLifecycle() async {
        let engine = SyntheticTranscriptionEngine()
        let sleeper = ControlledDebounceSleeper()
        let session = VoiceConversationSession(
            engine: engine,
            speechOutput: SyntheticSpeechOutput(),
            debounceSleeper: { duration in
                try await sleeper.sleep(for: duration)
            }
        )
        var staged: [String] = []
        var submitted: (String, ConversationTranscriptProvider)?
        session.onTranscriptStaged = { staged.append($0) }
        session.onFinalTranscript = { text, provider in
            submitted = (text, provider)
        }

        await session.start()
        engine.emit(.success(ConversationTranscriptResult(
            text: "Stable partial narration",
            isFinal: false
        )))
        await waitForSleeper(sleeper, count: 1)

        #expect(staged == ["Stable partial narration"])
        #expect(session.state == .listening)
        #expect(session.hasPendingSubmission)
        #expect(submitted == nil)
        #expect(await sleeper.requestedDurations() == [.seconds(2)])

        await sleeper.resumeNext()
        await settle()

        #expect(session.state == .thinking)
        #expect(submitted?.0 == "Stable partial narration")
        #expect(submitted?.1 == .syntheticFixture)
        #expect(!engine.isRunning)
    }

    @Test("Resumed speech cancels and restarts the two-second pause")
    func resumedSpeechRestartsDebounce() async {
        let engine = SyntheticTranscriptionEngine()
        let sleeper = ControlledDebounceSleeper()
        let session = VoiceConversationSession(
            engine: engine,
            speechOutput: SyntheticSpeechOutput(),
            debounceSleeper: { duration in
                try await sleeper.sleep(for: duration)
            }
        )
        var staged: [String] = []
        var submitted: [String] = []
        session.onTranscriptStaged = { staged.append($0) }
        session.onFinalTranscript = { text, _ in submitted.append(text) }

        await session.start()
        engine.emit(.success(ConversationTranscriptResult(
            text: "First segment",
            isFinal: false
        )))
        await waitForSleeper(sleeper, count: 1)

        engine.emit(.success(ConversationTranscriptResult(
            text: "First segment resumed",
            isFinal: false
        )))
        await waitForSleeperState(
            sleeper,
            requestedCount: 2,
            activeCount: 1
        )
        #expect(session.hasPendingSubmission)
        #expect(submitted.isEmpty)
        #expect(staged.last == "First segment resumed")
        #expect(await sleeper.requestedDurations() == [.seconds(2), .seconds(2)])

        await sleeper.resumeNext()
        await settle()
        #expect(submitted == ["First segment resumed"])
    }

    @Test("Pause and explicit cancellation remove a pending stale turn")
    func pauseCancelsPendingSubmission() async {
        let engine = SyntheticTranscriptionEngine()
        let sleeper = ControlledDebounceSleeper()
        let session = VoiceConversationSession(
            engine: engine,
            speechOutput: SyntheticSpeechOutput(),
            debounceSleeper: { duration in
                try await sleeper.sleep(for: duration)
            }
        )
        var cancelled = 0
        var submitted = 0
        session.onPendingTranscriptCancelled = { cancelled += 1 }
        session.onFinalTranscript = { _, _ in submitted += 1 }

        await session.start()
        engine.emit(.success(ConversationTranscriptResult(
            text: "Stale synthetic turn",
            isFinal: true
        )))
        await waitForSleeper(sleeper, count: 1)

        session.pause()
        await settle()

        #expect(session.state == .paused)
        #expect(!session.hasPendingSubmission)
        #expect(session.pendingSubmissionWindow == nil)
        #expect(session.transcriptPreview.isEmpty)
        #expect(cancelled == 1)
        #expect(submitted == 0)
        #expect(await sleeper.activeWaiterCount() == 0)
    }

    @Test("Pause, resume, optional speech, and interruption remain explicit")
    func controlsAreExplicit() async {
        let engine = SyntheticTranscriptionEngine()
        let speech = SyntheticSpeechOutput()
        let session = VoiceConversationSession(engine: engine, speechOutput: speech)

        await session.start()
        session.pause()
        #expect(session.state == .paused)
        #expect(!engine.isRunning)

        session.resume()
        #expect(session.state == .listening)

        session.spokenRepliesEnabled = true
        session.markThinking()
        session.handleReply("Synthetic reply")
        #expect(session.state == .responding)
        #expect(speech.spokenTexts == ["Synthetic reply"])

        session.interruptSpokenReply()
        #expect(speech.stopCount >= 1)
        #expect(session.state == .listening)
        #expect(engine.isRunning)
    }

    private func settle() async {
        for _ in 0..<4 {
            await Task.yield()
        }
    }

    private func waitForSleeper(
        _ sleeper: ControlledDebounceSleeper,
        count: Int
    ) async {
        for _ in 0..<100 {
            if await sleeper.activeWaiterCount() == count {
                return
            }
            await Task.yield()
        }
    }

    private func waitForSleeperState(
        _ sleeper: ControlledDebounceSleeper,
        requestedCount: Int,
        activeCount: Int
    ) async {
        for _ in 0..<100 {
            if await sleeper.requestedDurations().count == requestedCount,
               await sleeper.activeWaiterCount() == activeCount {
                return
            }
            await Task.yield()
        }
    }
}

private final class SyntheticTranscriptionEngine: ConversationTranscriptionEngine,
    @unchecked Sendable {
    let provider: ConversationTranscriptProvider?
    let supportsOnDeviceRecognition: Bool
    private(set) var isRunning = false
    var resultHandler: (@Sendable (
        Result<ConversationTranscriptResult, ConversationVoiceError>
    ) -> Void)?

    private let authorization: ConversationVoiceAuthorization
    private(set) var startCount = 0
    private(set) var stopCount = 0

    init(
        provider: ConversationTranscriptProvider? = .syntheticFixture,
        authorization: ConversationVoiceAuthorization = .authorized,
        supportsOnDeviceRecognition: Bool = true
    ) {
        self.provider = provider
        self.authorization = authorization
        self.supportsOnDeviceRecognition = supportsOnDeviceRecognition
    }

    func currentAuthorization() -> ConversationVoiceAuthorization {
        authorization
    }

    func requestAuthorization() async -> ConversationVoiceAuthorization {
        authorization
    }

    func start() throws {
        startCount += 1
        isRunning = true
    }

    func stop() {
        stopCount += 1
        isRunning = false
    }

    func emit(
        _ result: Result<ConversationTranscriptResult, ConversationVoiceError>
    ) {
        resultHandler?(result)
    }
}

private final class SyntheticSpeechOutput: ConversationSpeechOutput,
    @unchecked Sendable {
    private(set) var isSpeaking = false
    var completionHandler: (@Sendable () -> Void)?
    private(set) var spokenTexts: [String] = []
    private(set) var stopCount = 0

    func speak(_ text: String) {
        spokenTexts.append(text)
        isSpeaking = true
    }

    func stop() {
        stopCount += 1
        isSpeaking = false
    }
}

private final class SuspendedAuthorizationEngine: ConversationTranscriptionEngine,
    @unchecked Sendable {
    let provider: ConversationTranscriptProvider? = .syntheticFixture
    let supportsOnDeviceRecognition = true
    private(set) var isRunning = false
    var resultHandler: (@Sendable (
        Result<ConversationTranscriptResult, ConversationVoiceError>
    ) -> Void)?
    private(set) var startCount = 0
    private(set) var isAwaitingAuthorization = false
    private var authorizationContinuation:
        CheckedContinuation<ConversationVoiceAuthorization, Never>?

    func currentAuthorization() -> ConversationVoiceAuthorization {
        .notDetermined
    }

    func requestAuthorization() async -> ConversationVoiceAuthorization {
        await withCheckedContinuation { continuation in
            isAwaitingAuthorization = true
            authorizationContinuation = continuation
        }
    }

    func resolveAuthorization(_ value: ConversationVoiceAuthorization) {
        authorizationContinuation?.resume(returning: value)
        authorizationContinuation = nil
        isAwaitingAuthorization = false
    }

    func start() throws {
        startCount += 1
        isRunning = true
    }

    func stop() {
        isRunning = false
    }
}

private actor ControlledDebounceSleeper {
    private struct Waiter {
        let id: UUID
        let continuation: CheckedContinuation<Void, Error>
    }

    private var durations: [Duration] = []
    private var waiters: [Waiter] = []

    func sleep(for duration: Duration) async throws {
        let id = UUID()
        durations.append(duration)
        try Task.checkCancellation()
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                waiters.append(Waiter(id: id, continuation: continuation))
            }
        } onCancel: {
            Task {
                await self.cancel(id: id)
            }
        }
    }

    func requestedDurations() -> [Duration] {
        durations
    }

    func activeWaiterCount() -> Int {
        waiters.count
    }

    func resumeNext() {
        guard !waiters.isEmpty else { return }
        waiters.removeFirst().continuation.resume()
    }

    private func cancel(id: UUID) {
        guard let index = waiters.firstIndex(where: { $0.id == id }) else {
            return
        }
        waiters.remove(at: index).continuation.resume(throwing: CancellationError())
    }
}
