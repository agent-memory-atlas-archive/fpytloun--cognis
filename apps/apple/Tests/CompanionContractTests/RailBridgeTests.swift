import XCTest
@testable import CompanionContract

final class RailBridgeTests: XCTestCase {
    let generation = UUID().uuidString
    func decode(_ payload: [String: Any], type: String = "rail") throws -> BridgeMessage {
        let value: [String: Any] = ["version": 1, "generation": generation, "type": type, "payload": payload]
        // WKScriptMessage numbers arrive as Foundation JSON values, not Swift Int.
        let message = try JSONSerialization.jsonObject(with: JSONSerialization.data(withJSONObject: value))
        return try BridgeMessage.decode(message, generation: generation, trustedMainFrame: true)
    }
    func testRailCapabilitiesAreTypedAndBounded() throws {
        guard case .notificationSettings("status") = try decode(["action": "status"], type: "notification-settings")
        else { return XCTFail("Expected read-only status command") }
        XCTAssertThrowsError(try decode(["action": "enable"], type: "notification-settings"))
        guard case .rail("open", "agent-first", nil) = try decode(["action": "open", "agentId": "agent-first"])
        else { return XCTFail("Expected identifier-only open") }
        let invalid: [[String: Any]] = [
            ["action": "open", "agentId": "https://untrusted.invalid"],
            ["action": "navigate", "path": "/chat/first"],
            ["action": "drag-move", "delta": 0, "x": 50],
            ["action": "drag-move", "delta": 20001],
            ["action": "size", "width": 1000, "height": 50],
        ]
        for value in invalid { XCTAssertThrowsError(try decode(value)) }
        guard case .railSize(64, 110) = try decode(["action": "size", "width": 64, "height": 110])
        else { return XCTFail("Expected bounded window metrics") }
        guard case .panelState(nil, nil) = try decode(["agentId": NSNull(), "conversationId": NSNull()], type: "panel-state")
        else { return XCTFail("Expected explicit cleared selection") }
        XCTAssertThrowsError(try decode(["agentId": "agent-first", "conversationId": "/chat/first"], type: "panel-state"))
    }
}
