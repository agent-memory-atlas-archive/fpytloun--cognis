import XCTest
import WebKit
@testable import CognisCompanion

@MainActor
extension XCTestCase {
    func observeInlineBootstrap(in host: BundleWebView) {
        // Registered after the host's document-start configuration and before
        // any inline application code. No permission or network APIs are called.
        host.web.configuration.userContentController.addUserScript(WKUserScript(source: """
            (() => {
            const native = window.__cognisNative;
            const descriptor = Object.getOwnPropertyDescriptor(window, '__cognisNative');
            window.__inlineBootstrapObservation = {
              server: native?.server, version: native?.version, generation: native?.generation,
              frozen: !!native && Object.isFrozen(native),
              immutable: !!descriptor && !descriptor.writable && !descriptor.configurable,
              beforeApplication: typeof window.__cognisNativeReceive === 'undefined',
              origin: location.origin,
              notificationPermission: typeof Notification === 'undefined' ? 'unavailable' : Notification.permission
            };
            })();
            """, injectionTime: .atDocumentStart, forMainFrameOnly: true))
    }

    func assertInlineBootstrap(in host: BundleWebView,
                               file: StaticString = #filePath, line: UInt = #line) async throws {
        let result = try await host.web.evaluateJavaScript("""
            JSON.stringify({
              before: window.__inlineBootstrapObservation,
              origin: location.origin,
              root: !!window.__cognisNativeReceive,
              executableRequests: performance.getEntriesByType('resource')
                .filter(e => e.name.startsWith('cognisbundle:') && /\\.js(?:[?#]|$)/.test(e.name)).length,
              failures: (window.__cognisNativeStartupErrors || []).length,
              recovery: !!document.querySelector('#cognis-startup-recovery'),
              notificationPermission: typeof Notification === 'undefined' ? 'unavailable' : Notification.permission
            })
            """) as? String
        let json = try XCTUnwrap(result, file: file, line: line)
        let data = try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String: Any], file: file, line: line)
        let before = try XCTUnwrap(data["before"] as? [String: Any], file: file, line: line)
        XCTAssertEqual(before["server"] as? String, host.profile.origin.absoluteString, file: file, line: line)
        XCTAssertEqual(before["origin"] as? String, host.profile.origin.absoluteString, file: file, line: line)
        XCTAssertEqual(before["version"] as? Int, 1, file: file, line: line)
        XCTAssertEqual(before["generation"] as? String, host.generation, file: file, line: line)
        XCTAssertEqual(before["frozen"] as? Bool, true, file: file, line: line)
        XCTAssertEqual(before["immutable"] as? Bool, true, file: file, line: line)
        XCTAssertEqual(before["beforeApplication"] as? Bool, true, file: file, line: line)
        XCTAssertEqual(data["origin"] as? String, host.profile.origin.absoluteString, file: file, line: line)
        XCTAssertEqual(data["root"] as? Bool, true, file: file, line: line)
        XCTAssertEqual(data["executableRequests"] as? Int, 0, file: file, line: line)
        XCTAssertEqual(data["failures"] as? Int, 0, file: file, line: line)
        XCTAssertEqual(data["recovery"] as? Bool, false, file: file, line: line)
        XCTAssertEqual(data["notificationPermission"] as? String,
                       before["notificationPermission"] as? String, file: file, line: line)
        XCTAssertFalse(host.assets.served.keys.contains { $0.hasSuffix(".js") }, file: file, line: line)
        XCTAssertTrue(host.assets.failed.isEmpty, file: file, line: line)
    }
}
