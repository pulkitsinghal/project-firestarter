import Testing
@testable import OperationsFloater

@Suite("Queue race board")
struct QueueRaceTests {
    @Test("Adding steps moves progress backward without losing completed work")
    func addedStepsRegressTheSlider() throws {
        let before = record(
            id: "before",
            completed: 3,
            total: 4,
            active: 10,
            memory: 100,
            cpu: 10
        )
        let after = record(
            id: "after",
            completed: 3,
            total: 6,
            active: 10,
            memory: 100,
            cpu: 10
        )

        let beforeProgress = try #require(before.progressFraction)
        let afterProgress = try #require(after.progressFraction)
        #expect(beforeProgress == 0.75)
        #expect(afterProgress == 0.5)
        #expect(afterProgress < beforeProgress)
    }

    @Test("Every numeric sort is deterministic and leaves missing evidence last")
    func numericSortModes() {
        let records = [
            record(
                id: "middle",
                completed: 2,
                total: 4,
                active: 40,
                memory: 400,
                cpu: 20
            ),
            record(
                id: "high",
                completed: 4,
                total: 5,
                active: 10,
                memory: 800,
                cpu: 70
            ),
            QueueRecord(
                id: "missing",
                title: "Missing metrics",
                detail: "No runtime evidence.",
                state: .queued,
                exposure: .sanitized,
                verification: .unavailable
            ),
        ]

        #expect(
            QueueRaceSorter.sorted(records, by: .recentlyActive).map(\.id)
                == ["high", "middle", "missing"]
        )
        #expect(
            QueueRaceSorter.sorted(records, by: .finishFirst).map(\.id)
                == ["high", "middle", "missing"]
        )
        #expect(
            QueueRaceSorter.sorted(records, by: .memory).map(\.id)
                == ["high", "middle", "missing"]
        )
        #expect(
            QueueRaceSorter.sorted(records, by: .cpu).map(\.id)
                == ["high", "middle", "missing"]
        )
    }

    @Test("Needs-attention sorting raises waiting and unverifiable work")
    func attentionSort() {
        let ready = record(
            id: "ready",
            state: .ready,
            verification: .verified,
            completed: 5,
            total: 5,
            active: 5,
            memory: 50,
            cpu: 0
        )
        let running = record(
            id: "running",
            state: .running,
            verification: .verified,
            completed: 3,
            total: 5,
            active: 5,
            memory: 200,
            cpu: 20
        )
        let waiting = record(
            id: "waiting",
            state: .waiting,
            verification: .unavailable,
            completed: 1,
            total: 5,
            active: 7_200,
            memory: 10,
            cpu: 0
        )

        #expect(
            QueueRaceSorter.sorted(
                [ready, running, waiting],
                by: .needsAttention
            ).map(\.id) == ["waiting", "running", "ready"]
        )
    }

    @Test("Source order is preserved exactly")
    func sourceOrder() {
        let records = [
            record(id: "c", completed: 1, total: 4, active: 1, memory: 1, cpu: 1),
            record(id: "a", completed: 4, total: 4, active: 2, memory: 2, cpu: 2),
            record(id: "b", completed: 2, total: 4, active: 3, memory: 3, cpu: 3),
        ]

        #expect(
            QueueRaceSorter.sorted(records, by: .sourceOrder).map(\.id)
                == ["c", "a", "b"]
        )
    }

    private func record(
        id: String,
        state: QueueRecord.State = .running,
        verification: DashboardVerification = .verified,
        completed: Int,
        total: Int,
        active: Int,
        memory: Double,
        cpu: Double
    ) -> QueueRecord {
        QueueRecord(
            id: id,
            title: "Synthetic \(id)",
            detail: "Synthetic queue race record.",
            state: state,
            exposure: .sanitized,
            verification: verification,
            completedSteps: completed,
            totalSteps: total,
            currentStep: "Synthetic step",
            lastActiveSeconds: active,
            memoryMB: memory,
            cpuPercent: cpu
        )
    }
}
