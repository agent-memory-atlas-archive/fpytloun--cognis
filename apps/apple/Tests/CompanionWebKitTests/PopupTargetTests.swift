import XCTest
@testable import CognisCompanion

@MainActor
final class PopupTargetTests: XCTestCase {
    func testOnlyAvatarClickTogglesAnExistingPopup() {
        XCTAssertTrue(CompanionApp.shouldTogglePinnedPopup(visible: true, currentAgent: "agent-first",
            targetAgent: "agent-first", explicitConversation: nil))
        XCTAssertFalse(CompanionApp.shouldTogglePinnedPopup(visible: true, currentAgent: "agent-first",
            targetAgent: "agent-first", explicitConversation: "conversation-second"))
        XCTAssertFalse(CompanionApp.shouldTogglePinnedPopup(visible: true, currentAgent: "agent-first",
            targetAgent: "agent-second", explicitConversation: nil))
        XCTAssertFalse(CompanionApp.shouldTogglePinnedPopup(visible: false, currentAgent: "agent-first",
            targetAgent: "agent-first", explicitConversation: nil))
    }
}
