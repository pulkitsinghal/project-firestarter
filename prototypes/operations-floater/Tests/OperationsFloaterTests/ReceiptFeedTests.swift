import CryptoKit
import Foundation
import Testing
@testable import OperationsFloater

@Suite("Receipt feed")
struct ReceiptFeedTests {
    @Test("Reviewed dashboard handoff and canonical schemas remain pinned")
    func reviewedContractPins() throws {
        #expect(
            ReceiptFeedContractPins.reviewedSnapshotSHA256
                == "e0c598cdcc29ba39f509ccdb553f8d2c65709896827229e3aff1ada07c1bd1f2"
        )
        #expect(
            ReceiptFeedContractPins.reviewedLKGSnapshotSHA256
                == "ae4948b1c6396caca73a372a90474626d82d94291f36cb8bbc973799c6bebea8"
        )
        #expect(
            ReceiptFeedContractPins.reviewedManifestSHA256
                == "a94a8331b303189a99334b8c2f5940418a510326ceabbc1e58c34ee2460af1f8"
        )
        #expect(
            ReceiptFeedContractPins.canonicalManifestStateSHA256
                == "0a815cbd060d698b39badc715c16933436b7abec6588ca226bd1ffee4d73cc6a"
        )

        let packageRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let schemaRoot = packageRoot
            .appendingPathComponent("../../addons/orchestrator_session/common/")
            .appendingPathComponent("orchestrator-control/schemas")
            .standardizedFileURL
        #expect(
            try sha256(
                Data(contentsOf: schemaRoot.appendingPathComponent(
                    "receipt-feed-1.1.schema.json"
                ))
            ) == ReceiptFeedContractPins.feedSchemaSHA256
        )
        #expect(
            try sha256(
                Data(contentsOf: schemaRoot.appendingPathComponent(
                    "current-task-manifest-1.0.schema.json"
                ))
            ) == ReceiptFeedContractPins.manifestSchemaSHA256
        )
    }

    @Test("A valid current snapshot maps NOW, DECISIONS, and RECENTLY DONE")
    func validCurrentSnapshot() throws {
        let directory = try makeDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let data = try snapshotData(
            generatedAt: "2026-07-29T22:00:00Z",
            receipts: [
                receipt(label: "Current task", lifecycle: "active", lane: "running"),
                receipt(
                    label: "Owner decision",
                    lifecycle: "owner-gated",
                    lane: "owner-gated",
                    gate: "owner"
                ),
                receipt(label: "Accepted completion", lifecycle: "done", lane: "complete"),
            ]
        )
        try install(data, pointer: "receipt-feed-current.json", in: directory)

        let view = ReceiptFeedStore(directoryURL: directory).load(
            now: try #require(date("2026-07-29T22:00:30Z"))
        )

        #expect(view.pointerKind == .current)
        #expect(view.freshness == .current)
        #expect(view.now.map(\.publicLabel) == ["Current task"])
        #expect(view.decisions.map(\.publicLabel) == ["Owner decision"])
        #expect(view.recentlyDone.map(\.publicLabel) == ["Accepted completion"])
        #expect(view.sourceBadge == "CURRENT")
    }

    @Test("A fractional overrun is stale without hiding accepted receipts")
    func fractionalStaleBoundary() throws {
        let directory = try makeDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let data = try snapshotData(
            generatedAt: "2026-07-29T22:00:00.100Z",
            receipts: [
                receipt(label: "Still visible", lifecycle: "active", lane: "running")
            ],
            threshold: 60
        )
        try install(data, pointer: "receipt-feed-current.json", in: directory)

        let view = ReceiptFeedStore(directoryURL: directory).load(
            now: try #require(date("2026-07-29T22:01:01Z"))
        )

        #expect(view.freshness == .stale)
        #expect(view.ageSeconds == 61)
        #expect(view.now.map(\.publicLabel) == ["Still visible"])
        #expect(view.sourceBadge == "STALE")
    }

    @Test("Tampered current falls back to independently hashed LKG")
    func tamperedCurrentUsesLKG() throws {
        let directory = try makeDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let current = try snapshotData(
            generatedAt: "2026-07-29T22:00:00Z",
            receipts: [receipt(label: "Current", lifecycle: "active", lane: "running")]
        )
        let lkg = try snapshotData(
            generatedAt: "2026-07-29T21:00:00Z",
            receipts: [receipt(label: "Fallback", lifecycle: "done", lane: "complete")]
        )
        let currentSnapshot = try install(
            current,
            pointer: "receipt-feed-current.json",
            in: directory
        )
        try install(lkg, pointer: "receipt-feed-lkg.json", in: directory)
        try Data("tampered".utf8).write(to: currentSnapshot, options: .atomic)

        let view = ReceiptFeedStore(directoryURL: directory).load(
            now: try #require(date("2026-07-29T22:00:30Z"))
        )

        #expect(view.pointerKind == .lkg)
        #expect(view.recentlyDone.map(\.publicLabel) == ["Fallback"])
        #expect(view.sourceBadge == "LKG")
        #expect(view.reason?.contains("last known good") == true)
    }

    @Test("Unavailable current source status falls back to LKG")
    func unavailableCurrentUsesLKG() throws {
        let directory = try makeDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        var current = try #require(
            JSONSerialization.jsonObject(
                with: snapshotData(
                    generatedAt: "2026-07-29T22:00:00Z",
                    receipts: []
                )
            ) as? [String: Any]
        )
        var source = try #require(current["source"] as? [String: Any])
        source["sourceStatus"] = "unavailable"
        current["source"] = source
        try install(
            JSONSerialization.data(withJSONObject: current, options: [.sortedKeys]),
            pointer: "receipt-feed-current.json",
            in: directory
        )
        let lkg = try snapshotData(
            generatedAt: "2026-07-29T21:00:00Z",
            receipts: [receipt(label: "Fallback", lifecycle: "done", lane: "complete")]
        )
        try install(lkg, pointer: "receipt-feed-lkg.json", in: directory)

        let view = ReceiptFeedStore(directoryURL: directory).load(
            now: try #require(date("2026-07-29T22:00:30Z"))
        )

        #expect(view.pointerKind == .lkg)
        #expect(view.recentlyDone.map(\.publicLabel) == ["Fallback"])
    }

    @Test("Unknown fields and duplicate keys fail closed")
    func unknownAndDuplicateFieldsFailClosed() throws {
        let unknownDirectory = try makeDirectory()
        defer { try? FileManager.default.removeItem(at: unknownDirectory) }
        var unknown = try #require(
            JSONSerialization.jsonObject(
                with: snapshotData(generatedAt: "2026-07-29T22:00:00Z", receipts: [])
            ) as? [String: Any]
        )
        unknown["rawPrompt"] = "must not be accepted"
        try install(
            JSONSerialization.data(withJSONObject: unknown, options: [.sortedKeys]),
            pointer: "receipt-feed-current.json",
            in: unknownDirectory
        )
        #expect(
            ReceiptFeedStore(directoryURL: unknownDirectory).load().pointerKind == nil
        )

        let duplicateDirectory = try makeDirectory()
        defer { try? FileManager.default.removeItem(at: duplicateDirectory) }
        let valid = try snapshotData(
            generatedAt: "2026-07-29T22:00:00Z",
            receipts: []
        )
        let duplicate = Data(
            String(decoding: valid, as: UTF8.self)
                .replacingOccurrences(
                    of: #""schemaVersion":"1.1""#,
                    with: #""schemaVersion":"1.1","schemaVersion":"1.1""#
                )
                .utf8
        )
        try install(
            duplicate,
            pointer: "receipt-feed-current.json",
            in: duplicateDirectory
        )
        #expect(
            ReceiptFeedStore(directoryURL: duplicateDirectory).load().pointerKind == nil
        )
    }

    @Test("Schema mismatch, invalid hash, empty directory, and symlinks are unavailable")
    func failClosedSources() throws {
        let empty = try makeDirectory()
        defer { try? FileManager.default.removeItem(at: empty) }
        #expect(ReceiptFeedStore(directoryURL: empty).load() == .unavailable)

        let schemaDirectory = try makeDirectory()
        defer { try? FileManager.default.removeItem(at: schemaDirectory) }
        var schema = try #require(
            JSONSerialization.jsonObject(
                with: snapshotData(generatedAt: "2026-07-29T22:00:00Z", receipts: [])
            ) as? [String: Any]
        )
        schema["schemaVersion"] = "2.0"
        try install(
            JSONSerialization.data(withJSONObject: schema, options: [.sortedKeys]),
            pointer: "receipt-feed-current.json",
            in: schemaDirectory
        )
        #expect(ReceiptFeedStore(directoryURL: schemaDirectory).load().pointerKind == nil)

        let linkedDirectory = try makeDirectory()
        defer { try? FileManager.default.removeItem(at: linkedDirectory) }
        let outside = linkedDirectory.appendingPathComponent("outside.json")
        try Data("{}".utf8).write(to: outside)
        try FileManager.default.createSymbolicLink(
            at: linkedDirectory.appendingPathComponent("receipt-feed-current.json"),
            withDestinationURL: outside
        )
        #expect(ReceiptFeedStore(directoryURL: linkedDirectory).load().pointerKind == nil)
    }

    @Test("Nested receipt schema violations fail closed before projection")
    func nestedSchemaViolationFailsClosed() throws {
        let directory = try makeDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        var object = try #require(
            JSONSerialization.jsonObject(
                with: snapshotData(
                    generatedAt: "2026-07-29T22:00:00Z",
                    receipts: [
                        receipt(label: "Invalid metric", lifecycle: "active", lane: "running")
                    ]
                )
            ) as? [String: Any]
        )
        var receipts = try #require(object["receipts"] as? [[String: Any]])
        var duration = try #require(receipts[0]["duration"] as? [String: Any])
        duration["elapsedActiveSeconds"] = [
            "value": -1,
            "availability": "derived",
        ]
        receipts[0]["duration"] = duration
        object["receipts"] = receipts
        try install(
            JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]),
            pointer: "receipt-feed-current.json",
            in: directory
        )

        #expect(ReceiptFeedStore(directoryURL: directory).load().pointerKind == nil)
    }

    @Test("Feed absence never disables the established dashboard snapshot")
    @MainActor
    func feedAbsenceIsAdditive() throws {
        let directory = try makeDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let snapshotURL = directory.appendingPathComponent("dashboard-state.json")
        try Data(localDashboardFixture.utf8).write(to: snapshotURL)

        let state = DashboardState(
            snapshotURL: snapshotURL,
            receiptDirectoryURL: directory.appendingPathComponent("missing-receipts"),
            liveClient: nil
        )

        #expect(state.snapshot.queue.first?.title == "Existing race lane")
        #expect(state.snapshot.resourceBudget.first?.title == "Existing resource panel")
        #expect(state.receiptFeed == .unavailable)
        #expect(
            DashboardPanelActivity.shouldRefreshSnapshot(
                guideCollapsed: true,
                receiptsCollapsed: true,
                resourcesCollapsed: false,
                racesCollapsed: true,
                testsCollapsed: true,
                signalsCollapsed: true
            )
        )
    }

    private func makeDirectory() throws -> URL {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("ReceiptFeedTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true
        )
        return directory
    }

    @discardableResult
    private func install(
        _ snapshot: Data,
        pointer: String,
        in directory: URL
    ) throws -> URL {
        let digest = SHA256.hash(data: snapshot)
            .map { String(format: "%02x", $0) }
            .joined()
        let snapshotName = "receipt-feed-1.1.\(digest).json"
        let snapshotURL = directory.appendingPathComponent(snapshotName)
        try snapshot.write(to: snapshotURL, options: .atomic)
        let pointerObject: [String: Any] = [
            "schemaVersion": "1.1",
            "sha256": digest,
            "snapshot": snapshotName,
            "generatedAt": "2026-07-29T22:00:00Z",
        ]
        try JSONSerialization.data(withJSONObject: pointerObject, options: [.sortedKeys])
            .write(
                to: directory.appendingPathComponent(pointer),
                options: .atomic
            )
        return snapshotURL
    }

    private func snapshotData(
        generatedAt: String,
        receipts: [[String: Any]],
        threshold: Int = 300
    ) throws -> Data {
        let done = receipts.filter { ["done", "acknowledged"].contains($0["lifecycle"] as? String) }
        let active = receipts.filter {
            ["active", "setup-reserved"].contains($0["lifecycle"] as? String)
        }
        let ownerGated = receipts.filter { $0["lifecycle"] as? String == "owner-gated" }
        let object: [String: Any] = [
            "schemaVersion": "1.1",
            "source": [
                "generatedAt": generatedAt,
                "servedAt": generatedAt,
                "sourceStatus": "live",
                "freshness": [
                    "state": "current",
                    "ageSeconds": 0,
                    "thresholdSeconds": threshold,
                ],
                "sourceRevision": "native-consumer-fixture-1",
                "discrepancies": [],
                "provenance": [
                    "sourceClass": "pm-proxy-manifest",
                    "sanitization": "caller-allowlisted+projection-validated",
                    "rootExcluded": true,
                ],
            ],
            "capacity": [
                "configuredWorkers": 4,
                "rootExcluded": true,
                "availability": "derived",
            ],
            "counts": [
                "availability": "derived",
                "setupReserved": 0,
                "active": active.count,
                "waiting": 0,
                "ownerGated": ownerGated.count,
                "failed": 0,
                "done": done.count,
                "acknowledged": 0,
                "runnable": 0,
                "quarantined": 0,
            ],
            "receipts": receipts,
            "ownerGates": [],
            "quarantine": [],
        ]
        return try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
    }

    private func receipt(
        label: String,
        lifecycle: String,
        lane: String,
        gate: String = "none"
    ) -> [String: Any] {
        let checksum = label.utf8.reduce(0) { $0 + Int($1) } % 255
        let hex = String(
            repeating: String(format: "%02x", checksum),
            count: 32
        )
        return [
            "fingerprint": "rcpt_\(hex)",
            "revision": 1,
            "publicLabel": label,
            "ownerClass": gate == "owner" ? "owner" : "worker",
            "laneClass": lane,
            "metadataSource": lifecycle == "active" ? "launch" : "handback",
            "lifecycle": lifecycle,
            "gateKind": gate,
            "dependsOn": [],
            "acceptanceReceipts": [],
            "successorReceipts": [],
            "runnable": false,
            "duration": [
                "estimateSeconds": ["value": NSNull(), "availability": "unavailable"],
                "elapsedActiveSeconds": ["value": NSNull(), "availability": "unavailable"],
                "externalWaitSeconds": ["value": NSNull(), "availability": "unavailable"],
                "firstUsefulEvidenceSeconds": [
                    "value": NSNull(), "availability": "unavailable",
                ],
            ],
            "nextSafeMove": gate == "owner"
                ? "review-owner-gate"
                : (lifecycle == "active" ? "continue-active-work" : "verify-and-archive"),
            "evidenceAge": [
                "latestEvidenceAt": "2026-07-29T22:00:00Z",
                "ageSeconds": 0,
                "availability": "derived",
            ],
            "fieldAvailability": ["publicLabel": "supplied"],
            "evidenceRefs": [
                ["kind": "receipt", "ref": "fixture:receipt", "label": "Synthetic fixture"]
            ],
        ]
    }

    private func date(_ value: String) -> Date? {
        ISO8601DateFormatter().date(from: value)
    }

    private func sha256(_ data: Data) -> String {
        SHA256.hash(data: data)
            .map { String(format: "%02x", $0) }
            .joined()
    }

    private var localDashboardFixture: String {
        """
        {
          "schemaVersion": "1.0",
          "mode": "local",
          "queue": [{
            "id": "Q1",
            "title": "Existing race lane",
            "detail": "Existing feature remains available.",
            "state": "running",
            "exposure": "local-only",
            "verification": "verified"
          }],
          "tests": [],
          "resourceBudget": [{
            "id": "R1",
            "title": "Existing resource panel",
            "detail": "Existing feature remains available.",
            "displayValue": "Available",
            "exposure": "local-only",
            "verification": "verified"
          }],
          "signals": []
        }
        """
    }
}
