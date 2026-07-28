import Foundation

struct LoopbackOperationsSnapshotClient: Sendable {
    enum ClientError: Error, Equatable {
        case invalidResponse
        case rejected(Int)
        case responseTooLarge
        case invalidEnvelope
        case localModeRequired
    }

    static let metricsURL = URL(string: "http://127.0.0.1:11500/metrics")!
    static let maximumResponseBytes = 1_048_576

    private final class NoRedirectDelegate: NSObject, URLSessionTaskDelegate,
        @unchecked Sendable
    {
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

    func fetch() async throws -> DashboardSnapshot {
        let (data, response) = try await session.data(for: Self.makeRequest())
        return try Self.decode(data: data, response: response)
    }

    static func makeRequest() -> URLRequest {
        var request = URLRequest(url: metricsURL)
        request.httpMethod = "GET"
        request.timeoutInterval = 2
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("operations-floater", forHTTPHeaderField: "X-Client-App")
        return request
    }

    static func decode(data: Data, response: URLResponse) throws -> DashboardSnapshot {
        guard let response = response as? HTTPURLResponse else {
            throw ClientError.invalidResponse
        }
        guard response.statusCode == 200 else {
            throw ClientError.rejected(response.statusCode)
        }
        guard data.count <= maximumResponseBytes else {
            throw ClientError.responseTooLarge
        }
        guard
            let root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
            let operations = root["operations"] as? [String: Any]
        else {
            throw ClientError.invalidEnvelope
        }

        let operationsData = try JSONSerialization.data(
            withJSONObject: operations,
            options: [.sortedKeys]
        )
        let snapshot = try DashboardSnapshot.decodeValidated(from: operationsData)
        guard snapshot.mode == .local else {
            throw ClientError.localModeRequired
        }
        return snapshot
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
