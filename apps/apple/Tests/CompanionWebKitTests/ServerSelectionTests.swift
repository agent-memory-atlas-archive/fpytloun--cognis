import AppKit
import XCTest
import CompanionContract
@testable import CognisCompanion

@MainActor
private final class PromptFixture: ServerPrompting {
    var input: String?
    var requests: [String?] = []
    var failures = 0
    func request(current: String?, appName: String) -> String? {
        requests.append(current); return input
    }
    func invalidOrigin(appName: String) { failures += 1 }
}

@MainActor
final class ServerSelectionTests: XCTestCase {
    @objc private func chooseServerFixture() {}
    private func config(_ flavor: PackageFlavor) throws -> PackageConfiguration {
        var info: [String: Any] = ["CognisPackageFlavor": flavor.rawValue,
                                  "CFBundleIdentifier": flavor.bundleIdentifier]
        if flavor == .acceptance { info["CognisAcceptanceOrigin"] = "http://127.0.0.1:18763" }
        return try PackageConfiguration(info: info)
    }
    private func defaults() -> UserDefaults {
        let name = "cz.fpy.cognis.preview-tests." + UUID().uuidString
        let defaults = UserDefaults(suiteName: name)!
        addTeardownBlock { defaults.removePersistentDomain(forName: name) }
        return defaults
    }
    func testFreshExplicitPreviewPromptsEmptyAndCancelCannotLoadOldAcceptanceOrigin() throws {
        let prompt = PromptFixture(), preferences = defaults()
        let owner = ServerSelectionCoordinator(configuration: try config(.preview), defaults: preferences, prompt: prompt)
        XCTAssertNil(owner.initialSelection(background: false))
        XCTAssertEqual(prompt.requests.count, 1)
        XCTAssertNil(prompt.requests[0])
        XCTAssertNil(preferences.string(forKey: "server"))
        // No loader, WebKit instance or networking is created by selecting/cancelling.
        XCTAssertNil(owner.initialSelection(background: true))
        XCTAssertEqual(prompt.requests.count, 1)
    }
    func testInvalidURLAndCancelledChangePreserveExistingProfile() throws {
        let prompt = PromptFixture(), preferences = defaults(), configuration = try config(.preview)
        let owner = ServerSelectionCoordinator(configuration: configuration, defaults: preferences, prompt: prompt)
        let current = try configuration.profile("https://cognis.test")
        owner.remember(current)
        for invalid in ["", "http://cognis.test", "https://cognis.test/chat", "https://user:pass@cognis.test"] {
            prompt.input = invalid
            XCTAssertNil(owner.select(current: current))
        }
        XCTAssertEqual(prompt.failures, 4)
        prompt.input = nil
        XCTAssertNil(owner.select(current: current))
        XCTAssertEqual(preferences.string(forKey: "server"), current.origin.absoluteString)
        XCTAssertEqual(owner.initialSelection(background: false), current)
    }
    func testSameOwnerMakesEnabledAppAndTrayMenuItemsEvenWithoutSession() throws {
        let owner = ServerSelectionCoordinator(configuration: try config(.preview), defaults: defaults(), prompt: PromptFixture())
        // Both composition-root menus use this factory, independent of auth/snapshot.
        for key in ["", ","] {
            let item = try XCTUnwrap(owner.menuItem(target: self, action: #selector(chooseServerFixture), key: key))
            XCTAssertEqual(item.title, "Change Server…")
            XCTAssertTrue(item.isEnabled)
            XCTAssertEqual(item.keyEquivalent, key)
        }
    }
    func testAcceptanceIgnoresSavedServerAndCannotOpenPicker() throws {
        let preferences = defaults(), prompt = PromptFixture(), configuration = try config(.acceptance)
        preferences.set("https://cognis.test", forKey: "server")
        let owner = ServerSelectionCoordinator(configuration: configuration, defaults: preferences, prompt: prompt)
        XCTAssertEqual(owner.initialSelection(background: false)?.origin.absoluteString, "http://127.0.0.1:18763")
        XCTAssertNil(owner.select(current: nil))
        XCTAssertNil(owner.menuItem(target: self, action: #selector(chooseServerFixture), key: ""))
        XCTAssertTrue(prompt.requests.isEmpty)
        XCTAssertThrowsError(try configuration.profile("http://127.0.0.1:18762"))
        XCTAssertThrowsError(try configuration.profile("https://cognis.test"))
    }
    func testFlavorIdentityAndProfileIsolation() throws {
        let standard = try config(.standard), preview = try config(.preview), acceptance = try config(.acceptance)
        XCTAssertNotEqual(try standard.profile("http://127.0.0.1:18763").storageIdentifier,
                          try preview.profile("http://127.0.0.1:18763").storageIdentifier)
        XCTAssertNotEqual(try preview.profile("http://127.0.0.1:18763").storageIdentifier,
                          acceptance.fixedProfile?.storageIdentifier)
        XCTAssertEqual(try preview.profile("http://localhost:8080").origin.absoluteString, "http://localhost:8080")
        XCTAssertThrowsError(try PackageConfiguration(info: [
            "CognisPackageFlavor": "preview", "CFBundleIdentifier": PackageFlavor.preview.bundleIdentifier,
            "CognisAcceptanceOrigin": "http://127.0.0.1:18763",
        ]))
        XCTAssertThrowsError(try PackageConfiguration(info: [
            "CognisPackageFlavor": "preview", "CFBundleIdentifier": PackageFlavor.acceptance.bundleIdentifier,
        ]))
    }
}
