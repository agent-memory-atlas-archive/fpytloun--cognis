import XCTest
import UserNotifications
import CompanionContract
@testable import CognisCompanion

@MainActor
private final class NotificationFixture: NativeNotificationDelivering {
    var prompts = 0
    var added = 0
    var clears = 0
    var permissionResult = true
    var permissionError: Error?
    var status = "not-determined"
    func authorizationStatus() async -> String { status }
    var delayAuthorization = false
    var authorization: CheckedContinuation<Bool, Never>?
    func authorized() async -> Bool {
        if delayAuthorization { return await withCheckedContinuation { authorization = $0 } }
        await Task.yield()
        return true
    }
    func requestPermission() async throws -> Bool {
        prompts += 1
        if let permissionError { throw permissionError }
        return permissionResult
    }
    func add(identifier: String, review: NotificationReview, presentation: NotificationPresentation) async throws { added += 1 }
    func clear() { clears += 1 }
    func remove(identifier: String) {}
}

@MainActor
final class NativeNotificationTests: XCTestCase {
    func testUnsupportedCommunicationUsesStandardContentAndPreservesActions() throws {
        let presentation = try JSONDecoder().decode(NotificationPresentation.self, from: Data("""
        {"title":"Synthetic agent","subtitle":"Synthetic chat","body":"Ready for review.",
         "sender":null,
         "approval":{"actionId":"approval_fixture","revision":2,"submissionId":"\(UUID().uuidString)"}}
        """.utf8))
        let destination = try XCTUnwrap(NotificationTarget(kind: "chat", target: "conv_fixture"))
        let review = NotificationReview(profile: "https://notifications.fixture.invalid",
            account: "synthetic@fixture.invalid", destination: destination, scope: UUID().uuidString,
            approval: presentation.approval)
        XCTAssertTrue(presentation.isValid)
        XCTAssertTrue(review.isValid)
        XCTAssertEqual(SystemNotificationDelivery.communicationPresentation, "unavailable-standard-notifications")
        let content = try SystemNotificationDelivery.content(review: review, presentation: presentation, previews: true)
        XCTAssertEqual(content.title, "Synthetic agent")
        XCTAssertEqual(content.subtitle, "Synthetic chat")
        XCTAssertEqual(content.body, "Ready for review.")
        XCTAssertEqual(content.categoryIdentifier, "TOOL-APPROVAL")
        XCTAssertTrue(content.attachments.isEmpty)
        XCTAssertEqual(try JSONDecoder().decode(NotificationReview.self,
            from: XCTUnwrap(content.userInfo["review"] as? Data)).approval, presentation.approval)
        XCTAssertEqual(try SystemNotificationDelivery.content(review: review, presentation: presentation,
            previews: false).body, "Open Cognis to review.")
        let ordinary = try JSONDecoder().decode(NotificationPresentation.self, from: Data("""
        {"title":"Synthetic agent","subtitle":"Synthetic chat","body":"Done.",
         "sender":{"id":"agent_fixture","name":"Synthetic agent","png":null},"approval":null}
        """.utf8))
        XCTAssertTrue(ordinary.isValid)
        let ordinaryReview = NotificationReview(profile: review.profile, account: review.account,
            destination: destination, scope: review.scope)
        XCTAssertTrue(ordinaryReview.isValid)
        XCTAssertEqual(try SystemNotificationDelivery.content(review: ordinaryReview, presentation: ordinary,
            previews: true).categoryIdentifier, "COGNIS_REVIEW")
    }

    func testApprovalButtonsRequireUnlockAndRetiredScopesAreReviewOnly() throws {
        let category = try XCTUnwrap(NativeNotificationCoordinator.categories.first { $0.identifier == "TOOL-APPROVAL" })
        XCTAssertEqual(category.actions.map(\.identifier), ["approve", "deny"])
        XCTAssertTrue(category.actions.allSatisfy { $0.options.contains(.authenticationRequired) })
        let fixture = NotificationFixture()
        let owner = NativeNotificationCoordinator(delivery: fixture)
        let scope = UUID().uuidString
        owner.setScope(scope, account: "native@fixture.invalid", profile: "https://fixture.invalid")
        let approval = try JSONDecoder().decode(NotificationApproval.self, from:
            JSONSerialization.data(withJSONObject: ["actionId": "attention_fixture", "revision": 3, "submissionId": UUID().uuidString]))
        let review = NotificationReview(profile: "https://fixture.invalid", account: "native@fixture.invalid",
            destination: NotificationTarget(kind: "chat", target: "conv_fixture"), scope: scope, approval: approval)
        var actions = 0, reviews = 0
        owner.onAction = { _, _ in actions += 1 }
        owner.onReview = { _ in reviews += 1 }
        owner.respond(review, action: "approve")
        XCTAssertEqual(actions, 1)
        owner.invalidate()
        owner.respond(review, action: "approve")
        XCTAssertEqual(actions, 1); XCTAssertEqual(reviews, 1)
        owner.setScope(UUID().uuidString, account: "other@fixture.invalid", profile: "https://fixture.invalid")
        owner.respond(review, action: "deny")
        XCTAssertEqual(actions, 1); XCTAssertEqual(reviews, 2)
    }
    func testPermissionIsExplicitAndScopeDedupIsStable() async throws {
        let fixture = NotificationFixture()
        let owner = NativeNotificationCoordinator(delivery: fixture)
        let scope = UUID().uuidString
        owner.setScope(scope, account: "mac-companion@cognis.test", profile: "http://127.0.0.1:18762")
        let body: [String: Any] = ["version": 1, "generation": scope, "type": "notification",
            "payload": ["scope": scope, "id": "notification:inbox_native", "kind": "chat", "target": "conv_native",
                "presentation": ["title": "Synthetic agent", "subtitle": "Synthetic chat", "body": "Ready to review.",
                    "sender": NSNull(), "approval": NSNull()]]]
        guard case .notification(let intent) = try BridgeMessage.decode(body, generation: scope, trustedMainFrame: true)
        else { return XCTFail("Expected notification intent") }
        await owner.receive(intent); await owner.receive(intent)
        XCTAssertEqual(fixture.added, 1); XCTAssertEqual(fixture.prompts, 0)
        await owner.enableFromNativeMenu()
        XCTAssertEqual(fixture.prompts, 1)
        owner.invalidate(); await owner.receive(intent)
        XCTAssertEqual(fixture.added, 1)
    }
    func testNativeMenuDoesNotRequireAnActiveApplicationOrCurrentEvent() async {
        let fixture = NotificationFixture()
        let owner = NativeNotificationCoordinator(delivery: fixture)
        // The menu callback is the trust boundary; AppKit activity/event state
        // is deliberately absent from the authorization API.
        await owner.enableFromNativeMenu()
        XCTAssertEqual(fixture.prompts, 1)
        XCTAssertEqual(owner.permissionStatus, "Notifications enabled")
        fixture.permissionResult = false
        await owner.enableFromNativeMenu()
        XCTAssertTrue(owner.permissionStatus.hasPrefix("Notifications denied"))
        fixture.permissionError = NSError(domain: UNErrorDomain, code: 1)
        await owner.enableFromNativeMenu()
        XCTAssertEqual(owner.authorization, "not-determined")
        XCTAssertTrue(owner.permissionStatus.contains("UNErrorDomain, code 1"))
        XCTAssertTrue(owner.permissionStatus.contains("macOS did not allow"))
        fixture.permissionError = NSError(domain: NSCocoaErrorDomain, code: 1)
        await owner.enableFromNativeMenu()
        XCTAssertTrue(owner.permissionStatus.contains("NSCocoaErrorDomain, code 1"))
        XCTAssertFalse(owner.permissionStatus.contains("macOS did not allow"))
    }
    func testReadOnlyStatusNeverPromptsAndPreservesDeniedVsUnavailable() async {
        let fixture = NotificationFixture()
        let owner = NativeNotificationCoordinator(delivery: fixture)
        fixture.status = "denied"
        await owner.refreshPermission()
        XCTAssertEqual(owner.authorization, "denied")
        XCTAssertTrue(owner.permissionStatus.contains("Allow them in Notification Settings"))
        fixture.status = "unavailable"
        await owner.refreshPermission()
        XCTAssertEqual(owner.authorization, "unavailable")
        XCTAssertEqual(fixture.prompts, 0)
    }
    func testArbitraryDestinationsAreRejected() {
        XCTAssertFalse(NotificationTarget(kind: "approve", target: "conv_native").isValid)
        XCTAssertFalse(NotificationTarget(kind: "chat", target: "//untrusted.invalid").isValid)
    }
    func testLateAuthorizationCannotDeliverAfterLogout() async throws {
        let fixture = NotificationFixture()
        fixture.delayAuthorization = true
        let owner = NativeNotificationCoordinator(delivery: fixture)
        let scope = UUID().uuidString
        owner.setScope(scope, account: "mac-companion@cognis.test", profile: "http://127.0.0.1:18763")
        let body: [String: Any] = ["version": 1, "generation": scope, "type": "notification",
            "payload": ["scope": scope, "id": "notification:inbox_native", "kind": "chat", "target": "conv_native",
                "presentation": ["title": "Synthetic agent", "subtitle": "Synthetic chat", "body": "Ready to review.",
                    "sender": NSNull(), "approval": NSNull()]]]
        guard case .notification(let intent) = try BridgeMessage.decode(body, generation: scope, trustedMainFrame: true)
        else { return XCTFail("Expected intent") }
        let pending = Task { await owner.receive(intent) }
        while fixture.authorization == nil { await Task.yield() }
        owner.invalidate()
        fixture.authorization?.resume(returning: true)
        await pending.value
        XCTAssertEqual(fixture.added, 0)
        XCTAssertEqual(fixture.prompts, 0)
    }
}
