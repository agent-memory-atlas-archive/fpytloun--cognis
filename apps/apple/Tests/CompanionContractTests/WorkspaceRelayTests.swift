import XCTest
@testable import CompanionContract

@MainActor
final class WorkspaceRelayTests: XCTestCase {
    let main = UUID().uuidString, replica = UUID().uuidString
    let auth = UUID().uuidString, owner = UUID().uuidString
    func frame(kind: String, source: String, epoch: String?, revision: Int = 1) throws -> WorkspaceFrame {
        var body: [String: Any] = [
            "kind": kind, "document": source, "profile": "https://workspace.test", "account": "owner@workspace.test",
            "authEpoch": auth, "ownerEpoch": epoch as Any? ?? NSNull(), "target": "", "revision": revision, "id": 0
        ]
        if kind == "projection" {
            body["target"] = "*"
            body["projection"] = ["workspace": ["owner": "owner@workspace.test", "entries": [], "agents": []],
                                  "agents": [], "conversations": [:], "background": []] as [String: Any]
        } else if kind == "command" {
            body["id"] = 1; body["intent"] = ["type": "unpin", "key": "conversation:conv_first"]
        }
        return try WorkspaceFrame.decode(body)
    }
    func testOnlyLiveMainCanAnnounceAndOnlyMatchingAuthorityCanMutate() throws {
        let relay = WorkspaceRelay(profile: "https://workspace.test", main: main)
        let documents: Set<String> = [main, replica]
        var resets = 0
        let announce = try frame(kind: "projection", source: main, epoch: owner)
        XCTAssertEqual(relay.route(announce, source: main, documents: documents) { resets += 1 }, [replica])
        XCTAssertEqual(resets, 1)
        let command = try frame(kind: "command", source: replica, epoch: owner)
        XCTAssertEqual(relay.route(command, source: replica, documents: documents) {}, [main])
        XCTAssertTrue(relay.route(command, source: main, documents: documents) {}.isEmpty)
        XCTAssertTrue(relay.route(command, source: replica, documents: [main]) {}.isEmpty)
        let stale = try frame(kind: "command", source: replica, epoch: UUID().uuidString)
        XCTAssertTrue(relay.route(stale, source: replica, documents: documents) {}.isEmpty)
        let replacement = try frame(kind: "projection", source: main, epoch: UUID().uuidString)
        XCTAssertEqual(relay.route(replacement, source: main, documents: documents) { resets += 1 }, [replica])
        XCTAssertEqual(resets, 2)
        XCTAssertTrue(relay.route(announce, source: main, documents: documents) {}.isEmpty)
        XCTAssertTrue(relay.route(command, source: replica, documents: documents) {}.isEmpty)
    }
    func testRejectsArbitraryIntentAndProjectionWriters() throws {
        var command = try frame(kind: "command", source: replica, epoch: owner).value
        command["intent"] = ["type": "toggle", "url": "https://untrusted.test"]
        XCTAssertThrowsError(try WorkspaceFrame.decode(command))
        let relay = WorkspaceRelay(profile: "https://workspace.test", main: main)
        let forged = try frame(kind: "projection", source: replica, epoch: owner)
        XCTAssertTrue(relay.route(forged, source: replica, documents: [main, replica]) {}.isEmpty)
    }
}
