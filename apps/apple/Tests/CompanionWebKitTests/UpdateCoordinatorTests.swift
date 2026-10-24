import XCTest
import Sparkle
@testable import CognisCompanion

@MainActor
private final class UpdateFixture: UpdateDriving {
    var canCheck = true
    var automaticChecks = false, automaticInstall = false
    var starts = 0, checks = 0
    func start() throws { starts += 1 }
    func check() { checks += 1 }
}

@MainActor
final class UpdateCoordinatorTests: XCTestCase {
    func testUnavailableAndManagedNeverConstructUpdater() {
        for info: [String: Any] in [[:], ["CognisDistribution": "homebrew"]] {
            let owner = UpdateCoordinator(info: info, makeDriver: { _ in
                XCTFail("Must not construct updater without publisher/direct mode")
                return UpdateFixture()
            })
            XCTAssertFalse(owner.menu().items[1].isEnabled)
        }
    }
    func testSeparateOptInsAndExplicitCheckUseStandardAdapterBoundary() {
        let fixture = UpdateFixture()
        // Inert fixture configuration only: never constructs Sparkle or performs network I/O.
        let info: [String: Any] = ["SUFeedURL": "https://updates.cognis.test/appcast.xml",
            "SUPublicEDKey": Data(repeating: 0, count: 32).base64EncodedString(),
            "SURequireSignedFeed": true, "SUVerifyUpdateBeforeExtraction": true,
            "SUSignedFeedFailureExpirationInterval": 0]
        let owner = UpdateCoordinator(info: info, makeDriver: { _ in fixture })
        XCTAssertEqual(fixture.starts, 1)
        XCTAssertFalse(fixture.automaticChecks); XCTAssertFalse(fixture.automaticInstall)
        let menu = owner.menu()
        XCTAssertTrue(owner.responds(to: NSSelectorFromString("updaterShouldPromptForPermissionToCheckForUpdates:")))
        // Dispatch the actual menu selectors without NSApplication event routing
        // or a desktop session. Only the injected fixture receives the effects.
        _ = owner.perform(menu.items[2].action!, with: menu.items[2])
        XCTAssertTrue(fixture.automaticChecks); XCTAssertFalse(fixture.automaticInstall)
        _ = owner.perform(menu.items[3].action!, with: menu.items[3])
        XCTAssertTrue(fixture.automaticInstall)
        _ = owner.perform(menu.items[1].action!)
        XCTAssertEqual(fixture.checks, 1)
    }
}
