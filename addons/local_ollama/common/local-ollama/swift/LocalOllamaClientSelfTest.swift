import Foundation

// Offline self-test for LocalOllamaClient (no network, Foundation only).
//
// A mock OllamaTransport returns canned JSON so the request-building,
// response-decoding, loopback-guard, model-pinning, and typed-error paths are
// exercised with no running `ollama serve`. This has no XCTest dependency so it
// drops into any host Swift project; call `try await LocalOllamaClientSelfTest.run()`
// from a test target, a `main.swift`, or a `swift test` wrapper.
//
// (Firestarter itself does not compile Swift — no host SDKs — so this file is
// verified by the Python variant's parallel self-test and by structural checks;
// it is the reference implementation for consuming Swift projects.)

/// Records the last request and replays a scripted response (or a transport error).
final class MockOllamaTransport: OllamaTransport {
    var lastRequest: URLRequest?
    private let data: Data
    private let statusCode: Int
    private let contentType: String
    private let throwsTransportError: Bool

    init(json: Any = [:], statusCode: Int = 200,
         contentType: String = "application/json",
         throwsTransportError: Bool = false) {
        self.data = (try? JSONSerialization.data(withJSONObject: json)) ?? Data()
        self.statusCode = statusCode
        self.contentType = contentType
        self.throwsTransportError = throwsTransportError
    }

    func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        lastRequest = request
        if throwsTransportError {
            throw URLError(.cannotConnectToHost)
        }
        let response = HTTPURLResponse(
            url: request.url!, statusCode: statusCode, httpVersion: "HTTP/1.1",
            headerFields: ["Content-Type": contentType]
        )!
        return (data, response)
    }

    func sentBody() -> [String: Any] {
        guard let body = lastRequest?.httpBody,
              let object = try? JSONSerialization.jsonObject(with: body),
              let dict = object as? [String: Any] else { return [:] }
        return dict
    }
}

public enum LocalOllamaClientSelfTest {
    struct Failure: Error { let message: String }

    static func check(_ condition: Bool, _ message: String) throws {
        if !condition { throw Failure(message: "FAIL: \(message)") }
    }

    static func expect(_ expected: LocalOllamaError,
                       _ body: () async throws -> Void) async throws {
        do {
            try await body()
            throw Failure(message: "FAIL: expected \(expected) but nothing threw")
        } catch let error as LocalOllamaError where error == expected {
            return
        }
    }

    public static func run() async throws {
        // -- generate: request shape + typed response ----------------------
        let genTransport = MockOllamaTransport(
            json: ["model": "m", "response": "hi", "done": true])
        let genClient = try LocalOllamaClient(model: "m", transport: genTransport)
        let gen = try await genClient.generate(prompt: "say hi",
                                               options: ["temperature": .int(0)])
        let genBody = genTransport.sentBody()
        try check(genTransport.lastRequest?.url?.path == "/api/generate", "generate path")
        try check(genTransport.lastRequest?.httpMethod == "POST", "generate is POST")
        try check(genBody["stream"] as? Bool == false, "generate non-streaming")
        try check(genBody["model"] as? String == "m", "generate pins model")
        try check(gen.response == "hi" && gen.done, "generate typed response")

        // -- chat -----------------------------------------------------------
        let chatTransport = MockOllamaTransport(json: [
            "model": "m",
            "message": ["role": "assistant", "content": "yo"],
            "done": true,
        ])
        let chat = try await LocalOllamaClient(model: "m", transport: chatTransport)
            .chat(messages: [ChatMessage(role: "user", content: "hey")])
        try check(chatTransport.lastRequest?.url?.path == "/api/chat", "chat path")
        try check(chat.message.role == "assistant" && chat.message.content == "yo",
                  "chat typed response")

        // -- embeddings -----------------------------------------------------
        let embTransport = MockOllamaTransport(
            json: ["model": "e", "embedding": [0.1, 0.2, 0.3]])
        let emb = try await LocalOllamaClient(embedModel: "e", transport: embTransport)
            .embeddings(prompt: "text")
        try check(embTransport.lastRequest?.url?.path == "/api/embeddings", "embeddings path")
        try check(embTransport.sentBody()["model"] as? String == "e", "embeddings pins model")
        try check(emb.embedding == [0.1, 0.2, 0.3], "embeddings typed response")

        // -- loopback guard -------------------------------------------------
        do {
            _ = try LocalOllamaClient(host: "10.0.0.5", transport: MockOllamaTransport())
            throw Failure(message: "FAIL: non-loopback host should throw")
        } catch LocalOllamaError.endpointNotAllowed {
            // expected
        }
        _ = try LocalOllamaClient(host: "10.0.0.5", allowNonLoopback: true,
                                  transport: MockOllamaTransport())

        // -- error paths ----------------------------------------------------
        try await expect(.httpStatus(500)) {
            _ = try await LocalOllamaClient(
                transport: MockOllamaTransport(json: [:], statusCode: 500)
            ).generate(prompt: "x")
        }
        try await expect(.invalidContentType) {
            _ = try await LocalOllamaClient(
                transport: MockOllamaTransport(json: [:], contentType: "text/html")
            ).generate(prompt: "x")
        }
        try await expect(.transportFailed) {
            _ = try await LocalOllamaClient(
                transport: MockOllamaTransport(throwsTransportError: true)
            ).generate(prompt: "x")
        }
        try await expect(.malformedResponse) {
            _ = try await LocalOllamaClient(
                transport: MockOllamaTransport(json: ["unexpected": true])
            ).generate(prompt: "x")
        }

        print("PASS: LocalOllamaClient offline self-test (transport, typing, guards, errors)")
    }
}
