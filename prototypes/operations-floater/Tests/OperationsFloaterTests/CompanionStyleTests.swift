import Foundation
import Testing
@testable import OperationsFloater

@Suite("Companion style selector")
struct CompanionStyleTests {

    // MARK: - Cases and defaults

    @Test("Both styles ship and the default is the pet")
    func bothStylesShip() {
        #expect(CompanionStyle.allCases == [.pet, .human])
        #expect(CompanionStyle.default == .pet)
    }

    @Test("Raw values are stable so persisted selections survive upgrades")
    func rawValuesAreStable() {
        #expect(CompanionStyle.pet.rawValue == "pet")
        #expect(CompanionStyle.human.rawValue == "human")
        #expect(CompanionStyle.pet.id == "pet")
    }

    @Test("Each style names its companion and its menu label distinctly")
    func namesAndLabelsAreDistinct() {
        #expect(CompanionStyle.pet.companionName == "Ember")
        #expect(CompanionStyle.human.companionName == "Nova")
        #expect(CompanionStyle.pet.displayName != CompanionStyle.human.displayName)
        for style in CompanionStyle.allCases {
            #expect(!style.companionName.isEmpty)
            #expect(style.displayName.contains(style.companionName))
        }
    }

    // MARK: - Persistence round-trip

    @Test("A persisted raw value resolves back to its style; junk falls back to the default")
    func persistenceRoundTrip() {
        #expect(CompanionStyle(storedRawValue: "human") == .human)
        #expect(CompanionStyle(storedRawValue: "pet") == .pet)
        #expect(CompanionStyle(storedRawValue: nil) == .default)
        #expect(CompanionStyle(storedRawValue: "wolf") == .default)
        #expect(CompanionStyle(storedRawValue: "") == .default)
        #expect(CompanionStyle.storageKey == "OperationsFloater.CompanionStyleV1")
    }

    // MARK: - Chatter name

    @Test("Chatter resolves the companion name from the active style")
    func chatterNameFollowsStyle() {
        #expect(CompanionChatter.name(for: .pet) == "Ember")
        #expect(CompanionChatter.name(for: .human) == "Nova")
        // The bare constant remains the pet's name for existing call sites.
        #expect(CompanionChatter.name == "Ember")
    }

    // MARK: - Headless preview argument parsing

    @Test("The preview renderer parses an optional style, defaulting to the pet")
    func previewStyleParsing() {
        let base = ["OperationsFloater", "--render-companion-preview", "/tmp/out.png"]
        #expect(CompanionPreviewRenderer.requestedOutputPath(arguments: base) == "/tmp/out.png")
        #expect(CompanionPreviewRenderer.requestedStyle(arguments: base) == .pet)

        let human = base + ["--companion-style", "human"]
        #expect(CompanionPreviewRenderer.requestedStyle(arguments: human) == .human)

        let pet = base + ["--companion-style", "pet"]
        #expect(CompanionPreviewRenderer.requestedStyle(arguments: pet) == .pet)

        let garbage = base + ["--companion-style", "octopus"]
        #expect(CompanionPreviewRenderer.requestedStyle(arguments: garbage) == .pet)

        let dangling = base + ["--companion-style"]
        #expect(CompanionPreviewRenderer.requestedStyle(arguments: dangling) == .pet)
    }
}
