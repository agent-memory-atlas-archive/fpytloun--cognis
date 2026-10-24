import XCTest
@testable import CompanionContract

final class PlatformPolicyTests: XCTestCase {
    func testMissingAndManagedPublisherCannotUpdate() {
        XCTAssertEqual(UpdateAvailability(info: [:]), .unavailable)
        XCTAssertEqual(UpdateAvailability(info: ["CognisDistribution": "homebrew"]), .managed)
        XCTAssertEqual(UpdateAvailability(info: ["SUFeedURL": "http://127.0.0.1"]), .unavailable)
    }
    func testAcceptanceCannotReachM1OrProduction() throws {
        XCTAssertTrue(try ServerProfile("http://127.0.0.1:18763").isAcceptanceServer)
        XCTAssertFalse(try ServerProfile("http://127.0.0.1:18762").isAcceptanceServer)
        XCTAssertFalse(try ServerProfile("https://cognis.test").isAcceptanceServer)
    }
    func testCompatibilityDoesNotRequireMatchingRelease() {
        var value: [String: Any] = [
            "schema_version": 1, "product": ["id": "cognis"],
            "protocol": ["id": "cognis-client", "version": 1],
            "capabilities": ["authentication": 1, "chat": 2, "realtime": 1],
            "server": ["version": "another-release", "build_id": "another-build"]
        ]
        XCTAssertTrue(compatibleServer(value))
        value["capabilities"] = ["authentication": 1, "chat": 1, "realtime": 1]
        XCTAssertFalse(compatibleServer(value))
    }
}
