import XCTest
import CompanionContract

final class HTMLPreviewPolicyTests: XCTestCase {
    func testOnlyCanonicalSameProfileObjectURLs() throws {
        let profile = try ServerProfile("https://cognis.test:8443")
        let id = "6b3a438a-2580-491f-a51e-d7e0bbdc8fd5"
        XCTAssertTrue(isHTMLPreviewBlob(URL(string: "blob:https://cognis.test:8443/\(id)")!, profile: profile))
        for value in [
            "blob:null/\(id)", "blob:https://foreign.test:8443/\(id)",
            "blob:https://cognis.test:8443.evil/\(id)", "blob:https://cognis.test/\(id)",
            "blob:https://user@cognis.test:8443/\(id)", "blob:https://cognis.test:8443/\(id)#fragment",
            "blob:https://cognis.test:8443/\(id)?query", "blob:https://cognis.test:8443/not-a-uuid",
            "blob:https://cognis.test:8443//\(id)", "blob:https://cognis.test:8443/\(id)/extra",
            "https://cognis.test:8443/\(id)", "data:text/html,preview",
        ] {
            if let url = URL(string: value) {
                XCTAssertFalse(isHTMLPreviewBlob(url, profile: profile), value)
            }
        }
    }
}
