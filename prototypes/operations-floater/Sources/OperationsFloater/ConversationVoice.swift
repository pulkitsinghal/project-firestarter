import AVFoundation
import Combine
import Foundation
import Speech

struct ConversationTranscriptResult: Equatable, Sendable {
    let text: String
    let isFinal: Bool
}

enum ConversationVoiceAuthorization: String, Equatable, Sendable {
    case notDetermined
    case denied
    case restricted
    case authorized
}

enum ConversationVoiceState: String, Equatable, Sendable {
    case off
    case requestingPermission = "requesting-permission"
    case listening
    case paused
    case thinking
    case responding
    case unavailable

    var displayName: String {
        switch self {
        case .off:
            "Mic off"
        case .requestingPermission:
            "Requesting permission"
        case .listening:
            "Listening"
        case .paused:
            "Paused"
        case .thinking:
            "Thinking"
        case .responding:
            "Responding"
        case .unavailable:
            "Unavailable"
        }
    }
}

enum ConversationVoiceError: LocalizedError, Equatable {
    case permissionDenied
    case recognizerUnavailable
    case providerMetadataUnavailable
    case onDeviceRecognitionUnsupported
    case audioUnavailable

    var errorDescription: String? {
        switch self {
        case .permissionDenied:
            "Microphone and Speech Recognition permission are required."
        case .recognizerUnavailable:
            "On-device Speech Recognition is currently unavailable."
        case .providerMetadataUnavailable:
            "The transcription provider was not reported."
        case .onDeviceRecognitionUnsupported:
            "This Mac cannot provide on-device recognition for the selected language."
        case .audioUnavailable:
            "The microphone audio engine could not start."
        }
    }
}

protocol ConversationTranscriptionEngine: AnyObject, Sendable {
    var provider: ConversationTranscriptProvider? { get }
    var supportsOnDeviceRecognition: Bool { get }
    var isRunning: Bool { get }
    var resultHandler: (@Sendable (Result<ConversationTranscriptResult, ConversationVoiceError>)
        -> Void)? { get set }

    func currentAuthorization() -> ConversationVoiceAuthorization
    func requestAuthorization() async -> ConversationVoiceAuthorization
    func start() throws
    func stop()
}

protocol ConversationSpeechOutput: AnyObject, Sendable {
    var isSpeaking: Bool { get }
    var completionHandler: (@Sendable () -> Void)? { get set }
    func speak(_ text: String)
    func stop()
}

final class OnDeviceConversationTranscriber: NSObject, ConversationTranscriptionEngine,
    @unchecked Sendable {
    let provider: ConversationTranscriptProvider? = .onDevice
    var supportsOnDeviceRecognition: Bool {
        recognizer?.supportsOnDeviceRecognition == true
    }
    private(set) var isRunning = false
    var resultHandler: (@Sendable (Result<ConversationTranscriptResult, ConversationVoiceError>)
        -> Void)?

    private let recognizer: SFSpeechRecognizer?
    private let audioEngine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private var recognitionGeneration = 0

    init(locale: Locale = Locale(identifier: "en_US")) {
        recognizer = SFSpeechRecognizer(locale: locale)
        super.init()
    }

    func currentAuthorization() -> ConversationVoiceAuthorization {
        let speech = SFSpeechRecognizer.authorizationStatus()
        let microphone = AVCaptureDevice.authorizationStatus(for: .audio)
        if speech == .denied || microphone == .denied {
            return .denied
        }
        if speech == .restricted || microphone == .restricted {
            return .restricted
        }
        if speech == .authorized, microphone == .authorized {
            return .authorized
        }
        return .notDetermined
    }

    func requestAuthorization() async -> ConversationVoiceAuthorization {
        let microphoneGranted: Bool
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            microphoneGranted = true
        case .notDetermined:
            microphoneGranted = await AVCaptureDevice.requestAccess(for: .audio)
        case .denied, .restricted:
            microphoneGranted = false
        @unknown default:
            microphoneGranted = false
        }

        let speechStatus: SFSpeechRecognizerAuthorizationStatus
        if SFSpeechRecognizer.authorizationStatus() == .notDetermined {
            speechStatus = await withCheckedContinuation { continuation in
                SFSpeechRecognizer.requestAuthorization {
                    continuation.resume(returning: $0)
                }
            }
        } else {
            speechStatus = SFSpeechRecognizer.authorizationStatus()
        }

        guard microphoneGranted, speechStatus == .authorized else {
            return speechStatus == .restricted ? .restricted : .denied
        }
        return .authorized
    }

    func start() throws {
        guard !isRunning else { return }
        guard currentAuthorization() == .authorized else {
            throw ConversationVoiceError.permissionDenied
        }
        guard let recognizer, recognizer.isAvailable else {
            throw ConversationVoiceError.recognizerUnavailable
        }
        guard recognizer.supportsOnDeviceRecognition else {
            throw ConversationVoiceError.onDeviceRecognitionUnsupported
        }

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        request.taskHint = .dictation
        request.requiresOnDeviceRecognition = true
        self.request = request

        let input = audioEngine.inputNode
        let format = input.outputFormat(forBus: 0)
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 1_024, format: format) {
            [weak self] buffer, _ in
            self?.request?.append(buffer)
        }

        audioEngine.prepare()
        do {
            try audioEngine.start()
        } catch {
            input.removeTap(onBus: 0)
            self.request = nil
            throw ConversationVoiceError.audioUnavailable
        }
        isRunning = true

        recognitionGeneration += 1
        let generation = recognitionGeneration
        recognitionTask = recognizer.recognitionTask(with: request) {
            [weak self] result, error in
            guard let self, generation == recognitionGeneration else { return }
            if let result {
                let value = ConversationTranscriptResult(
                    text: result.bestTranscription.formattedString,
                    isFinal: result.isFinal
                )
                resultHandler?(.success(value))
                if result.isFinal {
                    teardownAudio()
                }
            }
            if error != nil {
                teardownAudio()
                resultHandler?(.failure(.recognizerUnavailable))
            }
        }
    }

    func stop() {
        recognitionGeneration += 1
        request?.endAudio()
        recognitionTask?.cancel()
        teardownAudio()
    }

    private func teardownAudio() {
        if audioEngine.isRunning {
            audioEngine.stop()
        }
        audioEngine.inputNode.removeTap(onBus: 0)
        request = nil
        recognitionTask = nil
        isRunning = false
    }
}

final class LocalConversationSpeechOutput: NSObject, ConversationSpeechOutput,
    AVSpeechSynthesizerDelegate, @unchecked Sendable {
    var isSpeaking: Bool { synthesizer.isSpeaking }
    var completionHandler: (@Sendable () -> Void)?

    private let synthesizer = AVSpeechSynthesizer()

    override init() {
        super.init()
        synthesizer.delegate = self
    }

    func speak(_ text: String) {
        stop()
        let utterance = AVSpeechUtterance(
            string: String(
                text.prefix(ConversationModuleContract.maximumReplyCharacters)
            )
        )
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate
        synthesizer.speak(utterance)
    }

    func stop() {
        if synthesizer.isSpeaking || synthesizer.isPaused {
            synthesizer.stopSpeaking(at: .immediate)
        }
    }

    func speechSynthesizer(
        _ synthesizer: AVSpeechSynthesizer,
        didFinish utterance: AVSpeechUtterance
    ) {
        completionHandler?()
    }

    func speechSynthesizer(
        _ synthesizer: AVSpeechSynthesizer,
        didCancel utterance: AVSpeechUtterance
    ) {
        // Cancellation is driven by explicit Stop/Interrupt or reply replacement.
        // The session owns the next state so a stale utterance cannot restart audio.
    }
}

@MainActor
final class VoiceConversationSession: ObservableObject {
    static let submissionPause: Duration = .seconds(2)

    @Published private(set) var state: ConversationVoiceState = .off
    @Published private(set) var authorization: ConversationVoiceAuthorization
    @Published private(set) var transcriptPreview = ""
    @Published private(set) var hasPendingSubmission = false
    @Published var spokenRepliesEnabled = false
    @Published private(set) var lastError: String?

    var onTranscriptStaged: ((String) -> Void)?
    var onFinalTranscript: ((String, ConversationTranscriptProvider) -> Void)?
    var onPendingTranscriptCancelled: (() -> Void)?

    private let engine: any ConversationTranscriptionEngine
    private let speechOutput: any ConversationSpeechOutput
    private let debounceSleeper: @Sendable (Duration) async throws -> Void
    private var conversationActive = false
    private var startGeneration = 0
    private var committedSegments: [String] = []
    private var pendingSubmissionTask: Task<Void, Never>?

    init(
        engine: any ConversationTranscriptionEngine =
            OnDeviceConversationTranscriber(),
        speechOutput: any ConversationSpeechOutput =
            LocalConversationSpeechOutput(),
        debounceSleeper: @escaping @Sendable (Duration) async throws -> Void = {
            try await Task.sleep(for: $0)
        }
    ) {
        self.engine = engine
        self.speechOutput = speechOutput
        self.debounceSleeper = debounceSleeper
        authorization = engine.currentAuthorization()
        installCallbacks()
    }

    deinit {
        pendingSubmissionTask?.cancel()
        engine.stop()
        speechOutput.stop()
    }

    func start() async {
        startGeneration += 1
        let generation = startGeneration
        conversationActive = false
        speechOutput.stop()
        lastError = nil
        state = .requestingPermission
        let status = await engine.requestAuthorization()
        guard generation == startGeneration,
              state == .requestingPermission else {
            return
        }
        authorization = status
        guard status == .authorized else {
            fail(.permissionDenied)
            return
        }
        guard let provider = engine.provider else {
            fail(.providerMetadataUnavailable)
            return
        }
        guard provider == .onDevice || provider == .syntheticFixture else {
            fail(.providerMetadataUnavailable)
            return
        }
        guard engine.supportsOnDeviceRecognition else {
            fail(.onDeviceRecognitionUnsupported)
            return
        }
        conversationActive = true
        startEngine()
    }

    func pause() {
        guard conversationActive, state == .listening else { return }
        cancelPendingSubmission()
        engine.stop()
        state = .paused
    }

    func resume() {
        guard conversationActive, state == .paused else { return }
        startEngine()
    }

    func stop() {
        startGeneration += 1
        conversationActive = false
        cancelPendingSubmission()
        engine.stop()
        speechOutput.stop()
        transcriptPreview = ""
        lastError = nil
        state = .off
    }

    func markThinking() {
        guard conversationActive else { return }
        pendingSubmissionTask?.cancel()
        pendingSubmissionTask = nil
        hasPendingSubmission = false
        engine.stop()
        state = .thinking
    }

    func cancelPendingSubmission() {
        let hadPendingContent =
            pendingSubmissionTask != nil
            || hasPendingSubmission
            || !committedSegments.isEmpty
            || !transcriptPreview.isEmpty
        pendingSubmissionTask?.cancel()
        pendingSubmissionTask = nil
        hasPendingSubmission = false
        committedSegments = []
        transcriptPreview = ""
        if hadPendingContent {
            onPendingTranscriptCancelled?()
        }
    }

    func handleReply(_ text: String) {
        guard conversationActive else { return }
        if spokenRepliesEnabled {
            state = .responding
            speechOutput.speak(text)
        } else {
            transcriptPreview = ""
            startEngine()
        }
    }

    func handleReplyFailure() {
        guard conversationActive else { return }
        transcriptPreview = ""
        startEngine()
    }

    func interruptSpokenReply() {
        guard conversationActive, state == .responding else { return }
        state = .thinking
        speechOutput.stop()
        transcriptPreview = ""
        startEngine()
    }

    private func installCallbacks() {
        engine.resultHandler = { [weak self] result in
            Task { @MainActor [weak self] in
                self?.apply(result)
            }
        }
        speechOutput.completionHandler = { [weak self] in
            Task { @MainActor [weak self] in
                guard let self,
                      self.conversationActive,
                      self.state == .responding else { return }
                self.transcriptPreview = ""
                self.startEngine()
            }
        }
    }

    private func startEngine() {
        do {
            try engine.start()
            state = .listening
            lastError = nil
        } catch let error as ConversationVoiceError {
            fail(error)
        } catch {
            fail(.audioUnavailable)
        }
    }

    private func apply(
        _ result: Result<ConversationTranscriptResult, ConversationVoiceError>
    ) {
        guard conversationActive else { return }
        switch result {
        case let .success(transcript):
            let boundedSegment = String(
                transcript.text.prefix(
                    ConversationModuleContract.maximumNarrationCharacters
                )
            ).trimmingCharacters(in: .whitespacesAndNewlines)
            guard !boundedSegment.isEmpty,
                  let provider = engine.provider,
                  provider == .onDevice || provider == .syntheticFixture else {
                return
            }
            pendingSubmissionTask?.cancel()
            pendingSubmissionTask = nil
            hasPendingSubmission = false

            if transcript.isFinal {
                committedSegments.append(boundedSegment)
            }
            let stagedText = boundedTranscript(
                partialSegment: transcript.isFinal ? nil : boundedSegment
            )
            transcriptPreview = stagedText
            onTranscriptStaged?(stagedText)

            scheduleSubmission(text: stagedText, provider: provider)
            if transcript.isFinal {
                startEngine()
            }
        case let .failure(error):
            fail(error)
        }
    }

    private func boundedTranscript(partialSegment: String?) -> String {
        let components = committedSegments + [partialSegment].compactMap { $0 }
        return String(
            components
                .joined(separator: " ")
                .prefix(ConversationModuleContract.maximumNarrationCharacters)
        )
    }

    private func scheduleSubmission(
        text: String,
        provider: ConversationTranscriptProvider
    ) {
        hasPendingSubmission = true
        pendingSubmissionTask = Task { [weak self, debounceSleeper] in
            do {
                try await debounceSleeper(Self.submissionPause)
                try Task.checkCancellation()
                guard let self, self.conversationActive else { return }
                self.pendingSubmissionTask = nil
                self.hasPendingSubmission = false
                self.committedSegments = []
                self.markThinking()
                self.onFinalTranscript?(text, provider)
            } catch {
                // Cancellation is expected whenever speech resumes or control changes.
            }
        }
    }

    private func fail(_ error: ConversationVoiceError) {
        startGeneration += 1
        cancelPendingSubmission()
        engine.stop()
        conversationActive = false
        state = .unavailable
        lastError = error.localizedDescription
    }
}
