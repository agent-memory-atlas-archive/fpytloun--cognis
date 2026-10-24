import XCTest
import CompanionContract
@testable import CognisCompanion

@MainActor
private final class LoginFixture: LoginServiceAdapting {
    var status: LoginRegistrationStatus = .notRegistered
    var registrations = 0, removals = 0
    var fail = false
    func register() throws {
        registrations += 1
        if fail { throw HostError.invalidMessage }
        status = .requiresApproval
    }
    func unregister() async throws {
        removals += 1
        if fail { throw HostError.invalidMessage }
        status = .notRegistered
    }
}

@MainActor
final class LoginCoordinatorTests: XCTestCase {
    func testRegistrationIsOptInAndActualStatusWins() async {
        let fixture = LoginFixture()
        let defaults = UserDefaults(suiteName: UUID().uuidString)!
        let owner = LoginCoordinator(service: fixture, defaults: defaults)
        _ = owner.menu()
        XCTAssertEqual(fixture.registrations, 0)
        await owner.setEnabled(true)
        XCTAssertEqual(owner.status, .requiresApproval)
        XCTAssertTrue(owner.explanation.contains("Approval required"))
        fixture.status = .enabled
        XCTAssertEqual(owner.menu().items[1].state, .on)
        fixture.status = .notRegistered
        XCTAssertEqual(owner.menu().items[1].state, .off)
        XCTAssertEqual(fixture.registrations, 1)
        fixture.fail = true
        await owner.setEnabled(true)
        XCTAssertEqual(owner.status, .notRegistered)
        XCTAssertTrue(owner.explanation.contains("failed"))
        fixture.fail = false; fixture.status = .enabled
        await owner.setEnabled(false)
        XCTAssertEqual(owner.status, .notRegistered)
        fixture.status = .notFound
        XCTAssertFalse(owner.menu().items[1].isEnabled)
        defaults.set(true, forKey: "startInBackground")
        let afterUpdate = LoginCoordinator(service: fixture, defaults: defaults)
        XCTAssertTrue(afterUpdate.startInBackground)
        XCTAssertEqual(fixture.registrations, 2)
    }
    func testLaunchAndResidentPolicy() {
        XCTAssertTrue(LaunchPolicy(loginItem: true, startInBackground: false).background)
        XCTAssertEqual(LaunchPolicy(loginItem: true, startInBackground: false).initialPath, "/companion")
        XCTAssertTrue(LaunchPolicy(loginItem: false, startInBackground: true).background)
        XCTAssertTrue(LaunchPolicy(loginItem: false, startInBackground: false).showMain)
        XCTAssertFalse(LaunchPolicy.terminateOnLastWindowClose)
    }
}
