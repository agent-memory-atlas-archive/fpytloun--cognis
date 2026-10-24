import XCTest
import WebKit
import AppKit
import CompanionContract
@testable import CognisCompanion

@MainActor
final class HTMLPreviewTests: XCTestCase {
    func testCompiledComponents() async throws {
        guard let fixture = ProcessInfo.processInfo.environment["COGNIS_HTML_COMPONENT_FIXTURE"] else {
            throw XCTSkip("Set COGNIS_HTML_COMPONENT_FIXTURE to the compiled fixture directory.")
        }
        let profile = try ServerProfile("https://html-preview.invalid",
            storageNamespace: "cz.fpy.cognis.tests.html-components-\(UUID())")
        let host = try BundleWebView(profile: profile, root: URL(fileURLWithPath: fixture))
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 900, height: 700),
                              styleMask: [.titled], backing: .buffered, defer: false)
        window.contentView = host.web; window.orderFront(nil)
        defer { host.invalidate(); window.orderOut(nil) }
        host.start(path: "/login")
        try await wait(host.web, "!!window.htmlPreviewFixture")
        _ = try await host.web.callAsyncJavaScript("return await htmlPreviewFixture.bootstrap();",
            arguments: [:], in: nil, contentWorld: .page)
        for surface in ["chat", "library", "inline", "project"] {
            _ = try await host.web.callAsyncJavaScript("return await htmlPreviewFixture.open(surface);",
                arguments: ["surface": surface], in: nil, contentWorld: .page)
            try await wait(host.web, "!!htmlPreviewFixture.state.report && htmlPreviewFixture.state.ticks >= 3")
            let value = try await host.web.evaluateJavaScript("htmlPreviewFixture.state.report")
            let report = try XCTUnwrap(value as? [String: Any])
            XCTAssertEqual(report["opaque"] as? Bool, true)
            XCTAssertEqual(report["nativeIdentityAbsent"] as? Bool, true)
            XCTAssertEqual(report["css"] as? String, "rgb(1, 2, 3)")
            if surface == "inline" {
                _ = try await host.web.evaluateJavaScript("htmlPreviewFixture.toggle()")
                try await wait(host.web, "document.querySelector('iframe') === null")
                try await assertStopped(host.web)
                _ = try await host.web.evaluateJavaScript("htmlPreviewFixture.state.report = null; htmlPreviewFixture.toggle()")
                try await wait(host.web, "!!htmlPreviewFixture.state.report")
            }
            _ = try await host.web.callAsyncJavaScript("return await htmlPreviewFixture.close();",
                arguments: [:], in: nil, contentWorld: .page)
            try await wait(host.web, "document.querySelector('iframe') === null")
            try await Task.sleep(for: .milliseconds(100))
            let before = try await host.web.evaluateJavaScript("htmlPreviewFixture.state.allTicks")
            try await Task.sleep(for: .milliseconds(150))
            let after = try await host.web.evaluateJavaScript("htmlPreviewFixture.state.allTicks")
            XCTAssertEqual(before as? Int, after as? Int, "Compiled child scripts cease after close")
            print("HTML_COMPONENT_PASS \(surface)")
        }
        _ = try await host.web.callAsyncJavaScript("""
            htmlPreviewFixture.holdBody();
            await htmlPreviewFixture.open('project');
            await new Promise(r => setTimeout(r, 100));
            await htmlPreviewFixture.close();
            htmlPreviewFixture.releaseBody();
            await new Promise(r => setTimeout(r, 100));
            return document.querySelector('iframe') === null;
            """, arguments: [:], in: nil, contentWorld: .page)
        try await wait(host.web, "document.querySelector('iframe') === null")
        try await assertStopped(host.web)
        let replacement = try await host.web.callAsyncJavaScript("""
            htmlPreviewFixture.holdBody();
            await htmlPreviewFixture.open('project');
            await new Promise(r => setTimeout(r, 100));
            await htmlPreviewFixture.open('inline');
            await new Promise(r => setTimeout(r, 100));
            const replacement = document.querySelector('iframe');
            htmlPreviewFixture.releaseBody();
            await new Promise(r => setTimeout(r, 150));
            return !!replacement && document.querySelectorAll('iframe').length === 1
              && document.querySelector('iframe') === replacement;
            """, arguments: [:], in: nil, contentWorld: .page)
        XCTAssertEqual(replacement as? Bool, true, "A stale pending project body cannot replace the current frame")
        _ = try await host.web.callAsyncJavaScript("return await htmlPreviewFixture.open('project');",
            arguments: [:], in: nil, contentWorld: .page)
        try await wait(host.web, "!!htmlPreviewFixture.state.report")
        _ = try await host.web.callAsyncJavaScript("return await htmlPreviewFixture.switchAccount();",
            arguments: [:], in: nil, contentWorld: .page)
        try await wait(host.web, "document.querySelector('iframe') === null")
        try await assertStopped(host.web)
        _ = try await host.web.callAsyncJavaScript("return await htmlPreviewFixture.open('library');",
            arguments: [:], in: nil, contentWorld: .page)
        try await wait(host.web, "!!htmlPreviewFixture.state.report")
        _ = try await host.web.callAsyncJavaScript("return await htmlPreviewFixture.logout();",
            arguments: [:], in: nil, contentWorld: .page)
        try await wait(host.web, "document.querySelector('iframe') === null")
        try await assertStopped(host.web)
        print("HTML_COMPONENT_LOGOUT_PASS")
    }

    private func assertStopped(_ web: WKWebView) async throws {
        try await Task.sleep(for: .milliseconds(100))
        let before = try await web.evaluateJavaScript("htmlPreviewFixture.state.allTicks")
        try await Task.sleep(for: .milliseconds(150))
        let after = try await web.evaluateJavaScript("htmlPreviewFixture.state.allTicks")
        XCTAssertEqual(before as? Int, after as? Int, "No stale child script activity after invalidation/removal")
    }

    private func wait(_ web: WKWebView, _ expression: String) async throws {
        for _ in 0..<100 {
            if (try? await web.evaluateJavaScript(expression)) as? Bool == true { return }
            try await Task.sleep(for: .milliseconds(50))
        }
        XCTFail("Timed out: \(expression)")
        throw NSError(domain: "HTMLPreviewAcceptance", code: 1, userInfo: [
            NSLocalizedDescriptionKey: "Timed out: \(expression)"
        ])
    }

    func testProductionBlobRenderingIsolationAndTeardown() async throws {
        guard let repo = ProcessInfo.processInfo.environment["COGNIS_HTML_TEST_REPO"] else {
            throw XCTSkip("Set COGNIS_HTML_TEST_REPO to the isolated source checkout.")
        }
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("cognis-html-preview-\(UUID())")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        try "<html><head></head><body><!-- __sveltekit_test.app.start( --></body></html>"
            .write(to: root.appendingPathComponent("index.html"), atomically: true, encoding: .utf8)
        let origin = "http://127.0.0.1:18794"
        let profile = try ServerProfile(origin, storageNamespace: "cz.fpy.cognis.tests.html-preview-\(UUID())")
        var externalCalls = 0
        let host = try BundleWebView(profile: profile, root: root, externalOpener: { _ in externalCalls += 1 })
        var nativeSinks = 0
        var childRefusals = 0
        host.onNativeAction = { action in
            switch action {
            case .externalOpen, .fileChooser, .download: nativeSinks += 1
            case .childNavigationRejected, .childFileChooserRejected: childRefusals += 1
            }
        }
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 800, height: 600),
                              styleMask: [.titled], backing: .buffered, defer: false)
        window.contentView = host.web; window.orderFront(nil)
        defer { host.invalidate(); window.orderOut(nil) }
        let source = try String(contentsOfFile: repo + "/ui/src/lib/attachments/html-preview.ts", encoding: .utf8)
        let probe = try String(contentsOfFile: repo + "/apps/apple/Fixtures/html-preview-probe.js", encoding: .utf8)
        let font = try Data(contentsOf: URL(fileURLWithPath: "/System/Library/Fonts/Supplemental/Arial.ttf")).base64EncodedString()
        var accepted = 0
        host.onMessage = { _ in accepted += 1 }
        let bridge: [String: Any] = ["version": 1, "generation": host.generation, "type": "dismiss", "payload": [:]]
        for mode in ["INLINE", "SIGNED"] {
            let marker = "export const \(mode)_HTML_POLICY = \""
            let policy = try XCTUnwrap(source.components(separatedBy: marker).dropFirst().first?.components(separatedBy: "\";").first)
            host.start(path: "/login")
            try await wait(host.web, "document.readyState === 'complete' && !window.previewReport && !window.closePreview && !!document.querySelector('meta[http-equiv]')")
            _ = try await host.web.callAsyncJavaScript("webkit.messageHandlers.cognis.postMessage(body); return true;",
                arguments: ["body": bridge], in: nil, contentWorld: .page)
            _ = try await host.web.callAsyncJavaScript(probe, arguments: [
                "policy": policy, "font": font, "origin": origin, "bridgeBody": bridge,
            ], in: nil, contentWorld: .page)
            try await wait(host.web, "!!window.previewReport && window.previewTicks >= 3")
            let value = try await host.web.evaluateJavaScript("window.previewReport")
            let report = try XCTUnwrap(value as? [String: Any])
            for key in ["heading", "css", "script", "nativeIdentityAbsent", "parentBlocked", "storageBlocked",
                        "cookieIsolated", "connectBlocked", "topBlocked", "popupBlocked", "opaque", "dataImage"] {
                XCTAssertEqual(report[key] as? Bool, true, "\(mode): \(key)")
            }
            for key in ["blobImage", "dataMedia", "blobMedia", "dataFont"] {
                XCTAssertEqual(report[key] as? Bool, mode == "SIGNED", "\(mode): \(key)")
            }
            XCTAssertEqual(accepted, mode == "INLINE" ? 1 : 2, "Only main frame bridge messages")
            let escaped = try await host.web.evaluateJavaScript("window.previewEscaped")
            XCTAssertEqual(escaped as? Bool, false)
            let cookie = try await host.web.evaluateJavaScript("document.cookie.includes('htmlPreview=parent')")
            XCTAssertEqual(cookie as? Bool, true)
            _ = try await host.web.evaluateJavaScript("window.closePreview()")
            try await Task.sleep(for: .milliseconds(100))
            let stopped = try await host.web.evaluateJavaScript("window.previewTicks")
            try await Task.sleep(for: .milliseconds(150))
            let after = try await host.web.evaluateJavaScript("window.previewTicks")
            XCTAssertEqual(stopped as? Int, after as? Int, "Removed frame stops executing")
            print("HTML_PRODUCTION \(mode) \(report)")
        }
        XCTAssertEqual(nativeSinks, 0, "Artifact attempts cannot enter native action sinks")
        XCTAssertEqual(externalCalls, 0)
        XCTAssertGreaterThan(childRefusals, 0, "Real WK callbacks must reach the rejecting delegate")
        print("HTML_NATIVE_SINKS childRefusals=\(childRefusals) external=\(externalCalls) sinks=\(nativeSinks)")
        _ = try await host.web.evaluateJavaScript("""
            const control = document.createElement('a');
            control.href = 'https://html-preview.invalid/control'; document.body.append(control); control.click();
            """)
        try await Task.sleep(for: .milliseconds(150))
        XCTAssertEqual(externalCalls, 1, "Trusted main link exercises the observable safe sink")
        XCTAssertEqual(nativeSinks, 1)
    }
}
