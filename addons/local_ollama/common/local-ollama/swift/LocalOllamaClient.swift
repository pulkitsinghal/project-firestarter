import Foundation

// Generic localhost Ollama HTTP client (Foundation only).
//
// The transport plumbing for talking to a local `ollama serve`: pin a model,
// POST a typed JSON body to one of the three stable endpoints
// (`/api/generate`, `/api/chat`, `/api/embeddings`) on
// http://{{ ollama_host }}:{{ ollama_port }}, decode a typed response, bound the
// time and the response size, and turn every failure mode into a typed error.
//
// It carries NO application logic — no prompts, no domain schema, no vision or
// document handling. Wire your own prompts/messages on top; keep this file as
// the one place the wire format and its gotchas live.
//
// Defaults come from firestarter tokens (`--set ollama_model=...` bakes in):
//   host  = {{ ollama_host }}   port = {{ ollama_port }}
//   model = {{ ollama_model }}  (generate / chat)
//   embed = {{ ollama_embed_model }}  (embeddings)

// MARK: - Transport

/// Injectable transport so the request/response handling can be unit-tested with
/// a mock — see LocalOllamaClientSelfTest.swift.
public protocol OllamaTransport {
    func data(for request: URLRequest) async throws -> (Data, URLResponse)
}

private final class NoRedirectDelegate: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)  // never follow a redirect for a local model call
    }
}

/// Content-silent loopback transport: no cache, cookies, credentials, proxy,
/// redirect following, or logging hook. Bounded request/resource timeouts.
public final class EphemeralLocalOllamaTransport: OllamaTransport {
    private let delegate = NoRedirectDelegate()
    private let session: URLSession

    public init(requestTimeout: TimeInterval = 180, resourceTimeout: TimeInterval = 240) {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.urlCache = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.httpCookieStorage = nil
        configuration.urlCredentialStorage = nil
        configuration.connectionProxyDictionary = [:]
        configuration.timeoutIntervalForRequest = requestTimeout
        configuration.timeoutIntervalForResource = resourceTimeout
        session = URLSession(configuration: configuration, delegate: delegate,
                             delegateQueue: nil)
    }

    public func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        try await session.data(for: request)
    }
}

// MARK: - Errors

public enum LocalOllamaError: Error, Equatable {
    case endpointNotAllowed          // host is not loopback and it wasn't opted in
    case transportFailed             // never produced an HTTP response
    case invalidHTTPResponse         // response was not an HTTPURLResponse
    case httpStatus(Int)             // non-200 status
    case invalidContentType          // not application/json
    case responseTooLarge            // exceeded maxResponseBytes
    case malformedResponse           // body was not the expected JSON shape
}

// MARK: - Typed responses

public struct GenerateResponse: Decodable, Equatable {
    public let model: String
    public let response: String
    public let done: Bool
}

public struct ChatMessage: Codable, Equatable {
    public let role: String
    public let content: String
    public init(role: String, content: String) {
        self.role = role
        self.content = content
    }
}

public struct ChatResponse: Decodable, Equatable {
    public let model: String
    public let message: ChatMessage
    public let done: Bool
}

public struct EmbeddingsResponse: Decodable, Equatable {
    public let model: String? // /api/embeddings does not always echo the model
    public let embedding: [Double]
}

// MARK: - Client

public struct LocalOllamaClient {
    public static let defaultHost = "{{ ollama_host }}"
    public static let defaultPort = {{ ollama_port }}
    public static let defaultModel = "{{ ollama_model }}"
    public static let defaultEmbedModel = "{{ ollama_embed_model }}"
    public static let loopbackHosts: Set<String> = ["{{ ollama_host }}", "::1", "localhost"]

    public let host: String
    public let port: Int
    public let model: String
    public let embedModel: String
    public let requestTimeout: TimeInterval
    public let maxResponseBytes: Int

    private let transport: OllamaTransport

    public init(host: String = defaultHost,
                port: Int = defaultPort,
                model: String = defaultModel,
                embedModel: String = defaultEmbedModel,
                requestTimeout: TimeInterval = 180,
                maxResponseBytes: Int = 16 * 1024 * 1024,
                allowNonLoopback: Bool = false,
                transport: OllamaTransport = EphemeralLocalOllamaTransport()) throws {
        if !allowNonLoopback && !Self.loopbackHosts.contains(host) {
            throw LocalOllamaError.endpointNotAllowed
        }
        self.host = host
        self.port = port
        self.model = model
        self.embedModel = embedModel
        self.requestTimeout = requestTimeout
        self.maxResponseBytes = maxResponseBytes
        self.transport = transport
    }

    public var baseURL: String { "http://\(host):\(port)" }

    // MARK: public API

    public func generate(prompt: String,
                         model: String? = nil,
                         system: String? = nil,
                         options: [String: JSONValue]? = nil,
                         keepAlive: String? = "5m") async throws -> GenerateResponse {
        let body = GenerateRequest(model: model ?? self.model, prompt: prompt,
                                   stream: false, system: system,
                                   options: options, keepAlive: keepAlive)
        return try await post(path: "/api/generate", body: body)
    }

    public func chat(messages: [ChatMessage],
                     model: String? = nil,
                     options: [String: JSONValue]? = nil,
                     keepAlive: String? = "5m") async throws -> ChatResponse {
        let body = ChatRequest(model: model ?? self.model, messages: messages,
                               stream: false, options: options, keepAlive: keepAlive)
        return try await post(path: "/api/chat", body: body)
    }

    public func embeddings(prompt: String,
                           model: String? = nil,
                           keepAlive: String? = "5m") async throws -> EmbeddingsResponse {
        let body = EmbeddingsRequest(model: model ?? self.embedModel,
                                     prompt: prompt, keepAlive: keepAlive)
        return try await post(path: "/api/embeddings", body: body)
    }

    // MARK: transport

    private func post<Request: Encodable, Response: Decodable>(
        path: String, body: Request
    ) async throws -> Response {
        guard let url = URL(string: baseURL + path) else {
            throw LocalOllamaError.transportFailed
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = requestTimeout
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.httpShouldHandleCookies = false
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        request.httpBody = try encoder.encode(body)

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await transport.data(for: request)
        } catch {
            throw LocalOllamaError.transportFailed
        }
        guard let http = response as? HTTPURLResponse else {
            throw LocalOllamaError.invalidHTTPResponse
        }
        guard http.statusCode == 200 else {
            throw LocalOllamaError.httpStatus(http.statusCode)
        }
        let contentType = (http.value(forHTTPHeaderField: "Content-Type") ?? "").lowercased()
        guard contentType.hasPrefix("application/json") else {
            throw LocalOllamaError.invalidContentType
        }
        guard data.count <= maxResponseBytes else {
            throw LocalOllamaError.responseTooLarge
        }
        guard let decoded = try? JSONDecoder().decode(Response.self, from: data) else {
            throw LocalOllamaError.malformedResponse
        }
        return decoded
    }
}

// MARK: - Request bodies

private struct GenerateRequest: Encodable {
    let model: String
    let prompt: String
    let stream: Bool
    let system: String?
    let options: [String: JSONValue]?
    let keepAlive: String?
    private enum CodingKeys: String, CodingKey {
        case model, prompt, stream, system, options
        case keepAlive = "keep_alive"
    }
}

private struct ChatRequest: Encodable {
    let model: String
    let messages: [ChatMessage]
    let stream: Bool
    let options: [String: JSONValue]?
    let keepAlive: String?
    private enum CodingKeys: String, CodingKey {
        case model, messages, stream, options
        case keepAlive = "keep_alive"
    }
}

private struct EmbeddingsRequest: Encodable {
    let model: String
    let prompt: String
    let keepAlive: String?
    private enum CodingKeys: String, CodingKey {
        case model, prompt
        case keepAlive = "keep_alive"
    }
}

// MARK: - Minimal JSON value for `options`

/// A tiny sum type so `options` (temperature, num_predict, …) can carry mixed
/// scalar types without pulling in a JSON dependency.
public enum JSONValue: Encodable, Equatable {
    case string(String)
    case int(Int)
    case double(Double)
    case bool(Bool)

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value): try container.encode(value)
        case .int(let value): try container.encode(value)
        case .double(let value): try container.encode(value)
        case .bool(let value): try container.encode(value)
        }
    }
}
