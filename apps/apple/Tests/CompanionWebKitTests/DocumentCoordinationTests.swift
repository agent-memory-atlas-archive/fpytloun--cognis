import XCTest
import AppKit
import WebKit
import CompanionContract

@MainActor
private final class DocumentLoaded: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
    let ready: XCTestExpectation
    init(_ ready: XCTestExpectation) { self.ready = ready }
    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        print("WK_TRACE navigation.start \(ObjectIdentifier(webView))")
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        print("WK_TRACE navigation.finish \(ObjectIdentifier(webView))"); ready.fulfill()
    }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        print("WK_TRACE navigation.fail \(ObjectIdentifier(webView)) \(error)")
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        print("WK_TRACE navigation.provisional.fail \(ObjectIdentifier(webView)) \(error)")
    }
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        print("WK_TRACE process.terminated \(ObjectIdentifier(webView))")
    }
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        print("WK_TRACE js \(message.body)")
    }
    deinit { print("WK_TRACE delegate.deinit") }
}

@MainActor
final class DocumentCoordinationTests: XCTestCase {
    private func call(_ web: WKWebView, _ method: String, _ args: [Any] = []) async throws -> Any? {
        print("WK_TRACE evaluation.start \(ObjectIdentifier(web)) \(method)")
        defer { print("WK_TRACE evaluation.end \(ObjectIdentifier(web)) \(method)") }
        // Always return a concrete serializable value. Some WebKit versions
        // cannot bridge an async undefined result through the Swift overlay.
        let result = try await web.callAsyncJavaScript(
            """
            try {
              const value = await window.documentFixture[method](...args);
              return JSON.stringify({value:value ?? null});
            } catch (error) {
              return JSON.stringify({failure:{name:error.name,message:error.message,stack:error.stack}});
            }
            """,
            arguments: ["method": method, "args": args], in: nil, contentWorld: .page)
        let data = try XCTUnwrap((result as? String)?.data(using: .utf8), method)
        let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        if let failure = object?["failure"] as? [String: Any] {
            throw NSError(domain: "DocumentFixture", code: 1,
                userInfo: [NSLocalizedDescriptionKey: "\(method): \(failure)"])
        }
        let value = object?["value"]
        return value is NSNull ? nil : value
    }
    private func status(_ web: WKWebView) async throws -> [String: Any] {
        try await call(web, "status") as? [String: Any] ?? [:]
    }
    private func awaitCount(_ web: WKWebView, _ key: String, _ count: Int) async throws {
        for _ in 0..<80 {
            if try await status(web)[key] as? Int == count { return }
            try await Task.sleep(for: .milliseconds(50))
        }
        XCTFail("Fixture operation did not start: \(key)")
    }
    func testTwoActualDocumentsCoordinateApplicationOwners() async throws {
        try await runDocuments(warmProfile: false)
    }
    func testWarmProfileDocumentsCoordinateApplicationOwners() async throws {
        try await runDocuments(warmProfile: true)
    }
    private func runDocuments(warmProfile: Bool) async throws {
        guard let path = ProcessInfo.processInfo.environment["COGNIS_DOCUMENT_FIXTURE"] else {
            throw XCTSkip("Set COGNIS_DOCUMENT_FIXTURE to the generated actual-owner inline fixture")
        }
        _ = NSApplication.shared
        let profile = try ServerProfile("https://documents.coordination.invalid",
            storageNamespace: "cz.fpy.cognis.tests.documents." + UUID().uuidString)
        let html = try String(contentsOfFile: path, encoding: .utf8)
        var views: [WKWebView] = []
        var delegates: [DocumentLoaded] = []
        var loaded: [XCTestExpectation] = []
        for _ in 0..<2 {
            let ready = expectation(description: "Inline document loaded")
            loaded.append(ready)
            let config = WKWebViewConfiguration()
            config.websiteDataStore = WKWebsiteDataStore(forIdentifier: profile.storageIdentifier)
            let delegate = DocumentLoaded(ready)
            config.userContentController.add(delegate, name: "documentTrace")
            config.userContentController.addUserScript(WKUserScript(source:
                "window.__cognisNative={server:'https://documents.coordination.invalid',generation:'fixture'};",
                injectionTime: .atDocumentStart, forMainFrameOnly: true))
            let web = WKWebView(frame: NSRect(x: 0, y: 0, width: 800, height: 600), configuration: config)
            delegates.append(delegate)
            web.navigationDelegate = delegate
            web.loadSimulatedRequest(URLRequest(url: profile.origin), responseHTML: html)
            views.append(web)
            if warmProfile {
                await fulfillment(of: [ready], timeout: 10)
                let boot = try await call(web, "bootstrap") as? String
                XCTAssertEqual(boot, "authenticated")
            }
        }
        let a = views[0], b = views[1]
        defer {
            for web in views {
                print("WK_TRACE teardown.start \(ObjectIdentifier(web))")
                web.stopLoading()
                web.navigationDelegate = nil
                web.configuration.userContentController.removeScriptMessageHandler(forName: "documentTrace")
                print("WK_TRACE teardown.finish \(ObjectIdentifier(web))")
            }
            _ = delegates
        }
        if !warmProfile {
        await fulfillment(of: loaded, timeout: 10)
        for web in views {
            for _ in 0..<100 {
                if try await web.evaluateJavaScript("typeof window.documentFixture === 'object'") as? Bool == true { break }
                try await Task.sleep(for: .milliseconds(50))
            }
            let boot = try await call(web, "bootstrap") as? String
            print("DOCUMENT_APPLICATION_BOOT \(boot ?? "missing")")
            XCTAssertEqual(boot, "authenticated")
        }
        }
        print("DOCUMENT_SCOPE_A \(String(describing: try await status(a)))")
        print("DOCUMENT_SCOPE_B \(String(describing: try await status(b)))")
        _ = try await call(a, "hold", ["refresh"])
        _ = try await call(a, "refresh")
        try await awaitCount(a, "refresh", 1)
        _ = try await call(b, "refresh")
        try await Task.sleep(for: .milliseconds(100))
        let queuedRefresh = try await status(b)["refresh"] as? Int
        XCTAssertEqual(queuedRefresh, 0)
        _ = try await call(a, "release", ["refresh"])
        let ar = try await call(a, "wait", ["refresh"]) as? String
        let br = try await call(b, "wait", ["refresh"]) as? String
        XCTAssertEqual(ar, "completed"); XCTAssertEqual(br, "completed")

        _ = try await call(a, "enqueue", ["shared-transaction"])
        _ = try await call(a, "hold", ["send"])
        _ = try await call(a, "send", ["shared-transaction"])
        try await awaitCount(a, "send", 1)
        _ = try await call(b, "drain")
        _ = try await call(a, "release", ["send"])
        _ = try await call(a, "wait", ["send"])
        _ = try await call(b, "wait", ["drain"])
        let receipt = try await call(b, "receipt", ["shared-transaction"]) as? String
        let siblingSends = try await status(b)["send"] as? Int
        XCTAssertEqual(receipt, "acked"); XCTAssertEqual(siblingSends, 0)

        _ = try await call(a, "enqueue", ["delayed-failure-transaction"])
        _ = try await call(a, "failNextSend")
        _ = try await call(a, "send", ["delayed-failure-transaction"])
        let failure = try await call(a, "wait", ["send"]) as? String
        XCTAssertEqual(failure, "rejected")
        _ = try await call(b, "send", ["delayed-failure-transaction"])
        _ = try await call(b, "wait", ["send"])
        let lateProjection = try await call(a, "delayedFailure", ["delayed-failure-transaction"]) as? [String: Any]
        XCTAssertEqual(lateProjection?["outcome"] as? String, "admitted")
        XCTAssertEqual(lateProjection?["failedEffects"] as? Int, 0)
        XCTAssertEqual(lateProjection?["state"] as? String, "acked")
        _ = try await call(a, "drain")
        _ = try await call(a, "wait", ["drain"])
        let unchangedSendCount = try await status(a)["send"] as? Int
        XCTAssertEqual(unchangedSendCount, 2)

        _ = try await call(a, "readDraft"); _ = try await call(b, "readDraft")
        _ = try await call(a, "writeDraft", ["submitted"])
        _ = try await call(b, "readDraft")
        _ = try await call(b, "writeDraft", ["newer sibling draft"])
        _ = try await call(a, "clearDraft", ["submitted"])
        _ = try await call(a, "writeDraft", ["stale edit"])
        let newer = try await call(b, "readDraft") as? String
        XCTAssertEqual(newer, "newer sibling draft")
        let legacyPreserved = try await call(a, "legacyNotice") as? Bool
        XCTAssertEqual(legacyPreserved, true)

        _ = try await call(a, "hold", ["upload"])
        let attachment = try await call(a, "stage") as! [String: Any]
        try await awaitCount(a, "upload", 1)
        _ = try await call(a, "resolveAttachment", [attachment])
        _ = try await call(b, "resolveAttachment", [attachment])
        _ = try await call(b, "prune")
        _ = try await call(a, "release", ["upload"])
        let au = try await call(a, "wait", ["upload"]) as? String
        let bu = try await call(b, "wait", ["upload"]) as? String
        let siblingUploads = try await status(b)["upload"] as? Int
        XCTAssertEqual(au, "completed"); XCTAssertEqual(bu, "completed")
        XCTAssertEqual(siblingUploads, 0)

        _ = try await call(a, "enqueue", ["late-transaction"])
        _ = try await call(a, "hold", ["send"])
        _ = try await call(a, "send", ["late-transaction"])
        try await awaitCount(a, "send", 3)
        _ = try await call(b, "logout")
        for _ in 0..<50 {
            if try await status(a)["auth"] as? String == "anonymous" { break }
            try await Task.sleep(for: .milliseconds(50))
        }
        let revoked = try await status(a)["auth"] as? String
        XCTAssertEqual(revoked, "anonymous")
        _ = try await call(a, "release", ["send"])
        let late = try await call(a, "wait", ["send"]) as? String
        XCTAssertEqual(late, "rejected")
        let secondAuth = try await call(b, "loginSecond") as? String
        XCTAssertEqual(secondAuth, "authenticated")
        let wrongReceipt = try await call(b, "receipt", ["late-transaction"]) as? String
        let wrongDraft = try await call(b, "readDraft") as? String
        XCTAssertEqual(wrongReceipt, "missing"); XCTAssertNil(wrongDraft)
        for web in views {
            let settled = try await call(web, "shutdown") as? Bool
            XCTAssertEqual(settled, true)
        }
        print("APPLICATION_DOCUMENTS_PASS: actual WK/IDB/locks/invalidation; injected network; no GUI/user profile")
    }
}
