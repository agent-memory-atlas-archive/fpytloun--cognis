import XCTest
import WebKit
import AppKit
import CompanionContract
@testable import CognisCompanion

@MainActor
final class HTTPSBootTests: XCTestCase {
    func testPackagedHTTPSLoginBootAndRetainedStore() async throws {
        guard let path = ProcessInfo.processInfo.environment["COGNIS_TEST_WEB_ROOT"] else {
            throw XCTSkip("Set COGNIS_TEST_WEB_ROOT to the actual generated Preview Web resources")
        }
        let profile = try ServerProfile("https://cognis-preview.invalid",
                                       storageNamespace: "cz.fpy.cognis.companion.preview.https-test-\(UUID())")
        let root = URL(fileURLWithPath: path)
        for pass in 0...1 {
            let host = try BundleWebView(profile: profile, root: root)
            observeInlineBootstrap(in: host)
            let ready = expectation(description: "Actual HTTPS Svelte root \(pass)")
            var didSignal = false
            var failure: String?
            host.onFailure = { failure = $0 }
            host.onMessage = { message in
                if case .snapshot = message, !didSignal { didSignal = true; ready.fulfill() }
            }
            let window = NSWindow(contentRect: NSRect(x: 30, y: 30, width: 1000, height: 760),
                                  styleMask: [.titled], backing: .buffered, defer: false)
            window.contentView = host.web
            window.orderFront(nil)
            host.start(path: "/login")
            await fulfillment(of: [ready], timeout: 20)
            for _ in 0..<50 {
                if try await host.web.evaluateJavaScript("!!document.querySelector('input[name=\"email\"]')") as? Bool == true {
                    break
                }
                try await Task.sleep(for: .milliseconds(100))
            }
            let result = try await host.web.evaluateJavaScript("""
                JSON.stringify({
                  origin:location.origin,
                  root:!!window.__cognisNativeReceive,
                  login:!!document.querySelector('input[name="email"]') && !!document.querySelector('input[name="password"]'),
                  failed:(window.__cognisNativeStartupErrors||[]).length,
                  executableRequests:performance.getEntriesByType('resource').filter(e=>/\\/_app\\/.*\\.js/.test(e.name)).length,
                  retained:localStorage.getItem('cognis-https-boot-test-draft')
                })
                """) as! String
            let data = try JSONSerialization.jsonObject(with: Data(result.utf8)) as! [String: Any]
            XCTAssertEqual(data["origin"] as? String, profile.origin.absoluteString)
            XCTAssertEqual(data["root"] as? Bool, true)
            XCTAssertEqual(data["login"] as? Bool, true)
            XCTAssertEqual(data["failed"] as? Int, 0)
            XCTAssertEqual(data["executableRequests"] as? Int, 0)
            XCTAssertNil(failure)
            try await assertInlineBootstrap(in: host)
            if pass == 0 {
                _ = try await host.web.evaluateJavaScript("localStorage.setItem('cognis-https-boot-test-draft','retained-test-draft')")
            } else {
                XCTAssertEqual(data["retained"] as? String, "retained-test-draft")
                if let snapshot = ProcessInfo.processInfo.environment["COGNIS_TEST_HTTPS_SNAPSHOT"] {
                    let image = try await host.web.takeSnapshot(configuration: nil)
                    if let tiff = image.tiffRepresentation,
                       let png = NSBitmapImageRep(data: tiff)?.representation(using: .png, properties: [:]) {
                        try png.write(to: URL(fileURLWithPath: snapshot))
                    }
                }
            }
            XCTAssertFalse(host.assets.served.keys.contains { $0.hasSuffix(".js") })
            host.invalidate()
            window.orderOut(nil)
        }
    }
}
