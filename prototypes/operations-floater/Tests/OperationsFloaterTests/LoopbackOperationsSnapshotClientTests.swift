import Foundation
import Testing
@testable import OperationsFloater

@Suite("Loopback operations snapshot")
struct LoopbackOperationsSnapshotClientTests {
    @Test("Metrics request is fixed to loopback without credentials")
    func requestIsFixedAndCredentialFree() {
        let request = LoopbackOperationsSnapshotClient.makeRequest()

        #expect(request.url == URL(string: "http://127.0.0.1:11500/metrics"))
        #expect(request.httpMethod == "GET")
        #expect(request.timeoutInterval == 2)
        #expect(request.value(forHTTPHeaderField: "X-Client-App") == "operations-floater")
        #expect(request.value(forHTTPHeaderField: "Authorization") == nil)
        #expect(request.httpBody == nil)
    }

    @Test("A verified local operations envelope drives real lane counts")
    func decodeLocalOperationsEnvelope() throws {
        let data = Data(
            """
            {
              "router": {"status": "online"},
              "operations": {
                "schemaVersion": "1.0",
                "mode": "local",
                "queue": [
                  {
                    "id": "router",
                    "title": "Router",
                    "detail": "Loopback service",
                    "state": "running",
                    "exposure": "local-only",
                    "verification": "verified"
                  }
                ],
                "tests": [],
                "resourceBudget": [],
                "signals": []
              }
            }
            """.utf8
        )

        let snapshot = try LoopbackOperationsSnapshotClient.decode(
            data: data,
            response: response(status: 200)
        )

        #expect(snapshot.mode == .local)
        #expect(snapshot.queue.map(\.id) == ["router"])
        #expect(snapshot.queue.first?.state == .running)
    }

    @Test("Missing operations and non-local modes fail closed")
    func invalidEnvelopeFailsClosed() {
        let missing = Data(#"{"router":{"status":"online"}}"#.utf8)
        #expect(throws: LoopbackOperationsSnapshotClient.ClientError.invalidEnvelope) {
            try LoopbackOperationsSnapshotClient.decode(
                data: missing,
                response: response(status: 200)
            )
        }

        let sample = Data(
            """
            {
              "operations": {
                "schemaVersion": "1.0",
                "mode": "sample",
                "queue": [],
                "tests": [],
                "resourceBudget": [],
                "signals": []
              }
            }
            """.utf8
        )
        #expect(throws: LoopbackOperationsSnapshotClient.ClientError.localModeRequired) {
            try LoopbackOperationsSnapshotClient.decode(
                data: sample,
                response: response(status: 200)
            )
        }
    }

    private func response(status: Int) -> HTTPURLResponse {
        HTTPURLResponse(
            url: LoopbackOperationsSnapshotClient.metricsURL,
            statusCode: status,
            httpVersion: "HTTP/1.1",
            headerFields: ["Content-Type": "application/json"]
        )!
    }
}
