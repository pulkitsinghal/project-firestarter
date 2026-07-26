import Foundation

struct LocalSnapshotStore {
    enum StoreError: LocalizedError, Equatable {
        case localModeRequired
        case previousSnapshotUnavailable
        case invalidSourceFile
        case sourceTooLarge

        var errorDescription: String? {
            switch self {
            case .localModeRequired:
                "The selected snapshot must use local mode."
            case .previousSnapshotUnavailable:
                "No valid previous local snapshot is available."
            case .invalidSourceFile:
                "The selected snapshot must be a regular local file."
            case .sourceTooLarge:
                "The selected snapshot exceeds the one-megabyte safety limit."
            }
        }
    }

    static let maximumSnapshotBytes = 1_048_576

    let snapshotURL: URL
    let previousSnapshotURL: URL

    init(snapshotURL: URL) {
        self.snapshotURL = snapshotURL
        previousSnapshotURL = snapshotURL
            .deletingPathExtension()
            .appendingPathExtension("previous.json")
    }

    func load() -> DashboardSnapshot? {
        guard let data = try? Data(contentsOf: snapshotURL) else { return nil }
        return try? DashboardSnapshot.decodeValidated(from: data)
    }

    func importLocalSnapshot(from sourceURL: URL) throws -> DashboardSnapshot {
        let values = try sourceURL.resourceValues(
            forKeys: [.fileSizeKey, .isRegularFileKey, .isSymbolicLinkKey]
        )
        guard values.isRegularFile == true, values.isSymbolicLink != true else {
            throw StoreError.invalidSourceFile
        }
        if let fileSize = values.fileSize, fileSize > Self.maximumSnapshotBytes {
            throw StoreError.sourceTooLarge
        }
        return try installLocalSnapshot(data: Data(contentsOf: sourceURL))
    }

    func installLocalSnapshot(data: Data) throws -> DashboardSnapshot {
        guard data.count <= Self.maximumSnapshotBytes else {
            throw StoreError.sourceTooLarge
        }
        let snapshot = try validatedLocalSnapshot(data)
        try prepareDirectory()

        if let currentData = try? Data(contentsOf: snapshotURL),
           (try? validatedLocalSnapshot(currentData)) != nil {
            try writeAtomically(currentData, to: previousSnapshotURL)
        }
        try writeAtomically(data, to: snapshotURL)
        return snapshot
    }

    func restorePreviousSnapshot() throws -> DashboardSnapshot {
        guard let previousData = try? Data(contentsOf: previousSnapshotURL),
              let previous = try? validatedLocalSnapshot(previousData) else {
            throw StoreError.previousSnapshotUnavailable
        }

        let currentData = try? Data(contentsOf: snapshotURL)
        try prepareDirectory()
        try writeAtomically(previousData, to: snapshotURL)
        if let currentData, (try? validatedLocalSnapshot(currentData)) != nil {
            try writeAtomically(currentData, to: previousSnapshotURL)
        }
        return previous
    }

    func hasValidPreviousSnapshot() -> Bool {
        guard let data = try? Data(contentsOf: previousSnapshotURL) else { return false }
        return (try? validatedLocalSnapshot(data)) != nil
    }

    private func validatedLocalSnapshot(_ data: Data) throws -> DashboardSnapshot {
        let snapshot = try DashboardSnapshot.decodeValidated(from: data)
        guard snapshot.mode == .local else {
            throw StoreError.localModeRequired
        }
        return snapshot
    }

    private func prepareDirectory() throws {
        let directory = snapshotURL.deletingLastPathComponent()
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o700],
            ofItemAtPath: directory.path
        )
    }

    private func writeAtomically(_ data: Data, to url: URL) throws {
        try data.write(to: url, options: .atomic)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o600],
            ofItemAtPath: url.path
        )
    }
}
