import XCTest
import WebKit
import AppKit
import CompanionContract
@testable import CognisCompanion

@MainActor
final class WebKitTests: XCTestCase {
    func testPackagedNativeIconWiring() throws {
        guard let root = ProcessInfo.processInfo.environment["COGNIS_TEST_WEB_ROOT"] else {
            throw XCTSkip("Set COGNIS_TEST_WEB_ROOT to the actual packaged Web directory.")
        }
        let resources = URL(fileURLWithPath: root).deletingLastPathComponent()
        let info = resources.deletingLastPathComponent().appendingPathComponent("Info.plist")
        let metadata = try PropertyListSerialization.propertyList(from: Data(contentsOf: info),
                                                                 options: [], format: nil) as? [String: Any]
        XCTAssertEqual(metadata?["CFBundleIconFile"] as? String, "Cognis.icns")
        let icon = try XCTUnwrap(NSImage(contentsOf: resources.appendingPathComponent("Cognis.icns")))
        XCTAssertGreaterThan(icon.representations.count, 1)
        for (name, pixels) in [("CognisMenuTemplate", 18), ("CognisMenuTemplate@2x", 36)] {
            let data = try Data(contentsOf: resources.appendingPathComponent(name + ".png"))
            let representation = try XCTUnwrap(NSBitmapImageRep(data: data))
            XCTAssertEqual(representation.pixelsWide, pixels)
            XCTAssertEqual(representation.pixelsHigh, pixels)
            XCTAssertTrue(representation.hasAlpha)
        }
        let template = try Data(contentsOf: resources.appendingPathComponent("CognisMenuTemplate.svg"))
        let master = try Data(contentsOf: URL(fileURLWithPath: root).appendingPathComponent("brand/cognis-mark.svg"))
        XCTAssertEqual(template, master, "Template must use canonical parent artwork exactly.")
    }

    func testPackagedColdStartAndReconstructionPreserveStorage() async throws {
        guard let root = ProcessInfo.processInfo.environment["COGNIS_TEST_WEB_ROOT"] else {
            throw XCTSkip("Set COGNIS_TEST_WEB_ROOT to the actual packaged Web directory.")
        }
        let profile = try ServerProfile(
            ProcessInfo.processInfo.environment["COGNIS_TEST_ORIGIN"] ?? "http://127.0.0.1:18763",
            storageNamespace: "cz.fpy.cognis.companion.tests.inline-http-\(UUID())")
        guard profile.isAcceptanceServer else {
            XCTFail("Packaged HTTP boot must use the isolated loopback origin."); return
        }
        let first = try BundleWebView(profile: profile, root: URL(fileURLWithPath: root))
        observeInlineBootstrap(in: first)
        let window = NSWindow(contentRect: NSRect(x: 80, y: 80, width: 1000, height: 760),
                              styleMask: [.titled], backing: .buffered, defer: false)
        window.contentView = first.web
        window.orderFront(nil)
        first.start(path: "/login")
        try await waitUntil(first) { "!!window.__cognisNativeReceive" }
        let recovered = try await first.web.evaluateJavaScript(
            "!!document.querySelector('#cognis-startup-recovery')") as? Bool
        XCTAssertEqual(recovered, false)
        try await assertInlineBootstrap(in: first)
        let key = "cognis-m1-native-reload-" + UUID().uuidString
        _ = try await first.web.callAsyncJavaScript("localStorage.setItem(key, 'preserved')",
                                                    arguments: ["key": key], in: nil, contentWorld: .page)
        first.invalidate()
        let second = try BundleWebView(profile: profile, root: URL(fileURLWithPath: root))
        observeInlineBootstrap(in: second)
        XCTAssertEqual(second.profile.storageIdentifier, first.profile.storageIdentifier)
        XCTAssertNotEqual(second.generation, first.generation)
        window.contentView = second.web
        defer { second.invalidate(); window.orderOut(nil) }
        second.start(path: "/login")
        try await waitUntil(second) { "!!window.__cognisNativeReceive" }
        let saved = try await second.web.callAsyncJavaScript(
            "const saved = localStorage.getItem(key); localStorage.removeItem(key); return saved;",
            arguments: ["key": key], in: nil, contentWorld: .page) as? String
        XCTAssertEqual(saved, "preserved")
        let afterReload = try await second.web.evaluateJavaScript(
            "!!document.querySelector('#cognis-startup-recovery')") as? Bool
        XCTAssertEqual(afterReload, false)
        try await assertInlineBootstrap(in: second)
        print("Packaged cold/reconstructed startup: no recovery overlay; localStorage preserved; no data clearing")
    }

    func testBundledApplicationBootsThroughRealLogin() async throws {
        guard let root = ProcessInfo.processInfo.environment["COGNIS_TEST_WEB_ROOT"],
              let origin = ProcessInfo.processInfo.environment["COGNIS_TEST_ORIGIN"] else {
            throw XCTSkip("Opt-in integration: set COGNIS_TEST_WEB_ROOT and loopback COGNIS_TEST_ORIGIN.")
        }
        let profile = try ServerProfile(origin)
        guard profile.origin.host == "127.0.0.1", profile.origin.port == 18763 else {
            XCTFail("Acceptance must target the isolated loopback Compose project."); return
        }
        let host = try BundleWebView(profile: profile, root: URL(fileURLWithPath: root))
        observeInlineBootstrap(in: host)
        // Only this explicitly opted-in acceptance profile, never a production store.
        await host.web.configuration.websiteDataStore.removeData(
            ofTypes: WKWebsiteDataStore.allWebsiteDataTypes(), modifiedSince: .distantPast)
        host.web.configuration.userContentController.addUserScript(WKUserScript(source: """
            window.__m1StartupFailures = [];
            document.addEventListener('securitypolicyviolation', e => {
              window.__m1StartupFailures.push({directive:e.violatedDirective, blocked:e.blockedURI});
            });
            window.addEventListener('error', e => {
              if (e.target?.src || e.target?.href) window.__m1StartupFailures.push({resource:e.target.src || e.target.href});
            }, true);
            """, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        let window = NSWindow(contentRect: NSRect(x: 80, y: 80, width: 1000, height: 760),
                              styleMask: [.titled], backing: .buffered, defer: false)
        window.contentView = host.web
        window.orderFront(nil)
        defer { host.invalidate(); window.orderOut(nil) }
        var received = false
        var lastSnapshot: Snapshot?
        host.onMessage = {
            received = true
            if case .snapshot(let value) = $0 { lastSnapshot = value }
        }
        host.onFailure = { message in XCTFail(message) }
        host.start(path: "/login")
        try await waitUntil(host) { "document.querySelector('input[type=email]') !== null" }
        let bootedWithoutRecovery = try await host.web.evaluateJavaScript(
            "document.querySelector('#cognis-startup-recovery') === null") as? Bool
        XCTAssertEqual(bootedWithoutRecovery, true)
        try await assertInlineBootstrap(in: host)
        print("Packaged boot: immutable configuration before application; no executable scheme requests, missing resources or recovery overlay")
        XCTAssertTrue(received, "The bundled main-frame bridge must be accepted.")
        let result = try await host.web.callAsyncJavaScript("""
            const email = document.querySelector('input[type=email]');
            const password = document.querySelector('input[type=password]');
            if (!email || !password) return false;
            email.value = 'mac-companion@cognis-e2e.localdev.me';
            email.dispatchEvent(new Event('input', {bubbles:true}));
            password.value = 'mac-companion-local-acceptance';
            password.dispatchEvent(new Event('input', {bubbles:true}));
            document.querySelector('form').requestSubmit();
            return true;
            """, arguments: [:], in: nil, contentWorld: .page) as? Bool
        XCTAssertEqual(result, true)
        print("Acceptance phase: login submitted")
        try await waitUntil(host) { "!location.pathname.startsWith('/login')" }
        let authenticated = try await host.web.callAsyncJavaScript("""
            const response = await fetch('/api/auth/me', {credentials:'include'});
            return response.ok;
            """, arguments: [:], in: nil, contentWorld: .page) as? Bool
        XCTAssertEqual(authenticated, true, "Normal cookie login must authenticate the real API.")
        print("Acceptance phase: authenticated HTTP")
        let refreshed = try await host.web.callAsyncJavaScript("""
            return (await fetch('/api/auth/refresh', {method:'POST', credentials:'include'})).ok;
            """, arguments: [:], in: nil, contentWorld: .page) as? Bool
        XCTAssertEqual(refreshed, true)
        print("Acceptance phase: refreshed")
        let socketAuthenticated = try await host.web.callAsyncJavaScript("""
            return await new Promise(resolve => {
              const socket = new WebSocket(location.origin.replace('http:', 'ws:') + '/api/ws');
              const timer = setTimeout(() => {socket.close(); resolve(false);}, 5000);
              socket.onmessage = e => {
                const frame = JSON.parse(e.data);
                if (frame.type === 'authenticated') {clearTimeout(timer); socket.close(); resolve(true);}
              };
              socket.onerror = () => {clearTimeout(timer); resolve(false);};
            });
            """, arguments: [:], in: nil, contentWorld: .page) as? Bool
        XCTAssertEqual(socketAuthenticated, true)
        print("Acceptance phase: authenticated WebSocket")
        let persistent = try await host.web.callAsyncJavaScript("""
            localStorage.setItem('cognis-m1-acceptance', 'persisted');
            return await new Promise((resolve, reject) => {
              const r = indexedDB.open('cognis-m1-acceptance', 1);
              r.onupgradeneeded = () => r.result.createObjectStore('probe');
              r.onsuccess = () => { r.result.close(); resolve(true); };
              r.onerror = () => reject(r.error);
            });
            """, arguments: [:], in: nil, contentWorld: .page) as? Bool
        XCTAssertEqual(persistent, true)
        print("Acceptance phase: IndexedDB")
        host.send(["type": "navigate", "path": "/chat/new?agent_id=e2e-test-agent"])
        try await waitUntil(host) { "location.pathname === '/chat/new'" }
        try await waitUntil(host) { "[...document.querySelectorAll('button')].some(b => b.textContent.trim() === 'Create conversation' && !b.disabled)" }
        _ = try await host.web.evaluateJavaScript("""
            [...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Create conversation').click()
            """)
        try await waitUntil(host) { "location.pathname.startsWith('/chat/') && location.pathname !== '/chat/new' && !!document.querySelector('textarea')" }
        let path = try await host.web.evaluateJavaScript("location.pathname") as! String
        print("Acceptance phase: conversation route and composer mounted")
        _ = try await host.web.callAsyncJavaScript("""
            const id = location.pathname.split('/').pop();
            const snapshot = await fetch('/api/v1/chat/v2/conversations/' + id + '/snapshot', {credentials:'include'});
            if (!snapshot.ok) throw new Error('Chat snapshot not ready');
            await new Promise(resolve => setTimeout(resolve, 500));
            return true;
            """, arguments: [:], in: nil, contentWorld: .page)
        _ = try await host.web.callAsyncJavaScript("""
            const composer = document.querySelector('textarea');
            composer.value = 'Hello from the bundled Mac acceptance test.';
            composer.dispatchEvent(new Event('input', {bubbles:true}));
            return true;
            """, arguments: [:], in: nil, contentWorld: .page)
        try await waitUntil(host) { "!!document.querySelector('button[aria-label=\"Send\"]:not(:disabled)')" }
        _ = try await host.web.evaluateJavaScript("document.querySelector('button[aria-label=\"Send\"]').click()")
        print("Acceptance phase: send clicked")
        try await waitUntil(host) { "document.querySelectorAll('[data-kind=\"message\"][data-role=\"assistant\"]').length >= 1" }
        print("Acceptance phase: rendered assistant found")
        try await waitUntil(host) {
            """
            [...document.querySelectorAll('[data-kind="message"][data-role="assistant"]')].some(element => {
              const bounds = element.getBoundingClientRect();
              return element.dataset.streaming === 'false' && element.dataset.stable === 'true'
                && element.innerText.trim().length > 0 && bounds.width > 0 && bounds.height > 0;
            })
            """
        }
        print("Acceptance phase: visible nonempty settled assistant response")
        let userMessages = try await host.web.evaluateJavaScript(
            "document.querySelectorAll('[data-kind=\"message\"][data-role=\"user\"]').length") as? Int
        XCTAssertEqual(userMessages, 1)
        print("Acceptance phase: one rendered user message")
        _ = try await host.web.evaluateJavaScript("document.querySelector('[data-testid=\"pin-conversation\"]').click()")
        print("Acceptance phase: pin clicked")
        for _ in 0..<30 {
            if lastSnapshot?.pins.count == 1 { break }
            try await Task.sleep(for: .milliseconds(200))
        }
        XCTAssertEqual(lastSnapshot?.pins.first?.path, path + "?window=1")
        host.send(["type": "navigate", "path": "/native-pinned?agent=e2e-test-agent&conversation=" + String(path.split(separator: "/").last!)])
        try await waitUntil(host) {
            "!!document.querySelector('[data-testid=\"native-pinned-surface\"] [data-testid=\"pinned-chat-panel\"]') && !!document.querySelector('textarea')"
        }
        let canonical = try await host.web.evaluateJavaScript("""
            !!document.querySelector('[role="tab"][aria-label="Home"]')
              && !!document.querySelector('[aria-label="Find conversation"]')
              && !!document.querySelector('[aria-label="Open full conversation"]')
              && !document.querySelector('[aria-label="Conversation information"]')
              && !document.querySelector('[data-testid="pinned-conversation-dock"]')
            """) as? Bool
        XCTAssertEqual(canonical, true, "Native must host the actual pinned tree without application/page chrome.")
        _ = try await host.web.callAsyncJavaScript("""
            const composer = document.querySelector('textarea');
            composer.value = 'Unsent Mac acceptance draft';
            composer.dispatchEvent(new Event('input', {bubbles:true}));
            return true;
            """, arguments: [:], in: nil, contentWorld: .page)
        print("Acceptance phase: draft entered")
        host.send(["type": "visibility", "visible": false, "focused": false])
        host.send(["type": "visibility", "visible": true, "focused": true])
        try await waitUntil(host) { "document.querySelector('textarea')?.value === 'Unsent Mac acceptance draft'" }
        XCTAssertTrue(host.web.url.map(profile.contains) == true)
    }

    private func waitUntil(_ host: BundleWebView, expression: () -> String) async throws {
        let script = expression()
        for _ in 0..<100 {
            if let ready = try? await host.web.evaluateJavaScript(script) as? Bool, ready { return }
            try await Task.sleep(for: .milliseconds(200))
        }
        XCTFail("Timed out waiting for bundled application integration boundary: \(script)")
        let diagnostic = try? await host.web.evaluateJavaScript("""
            JSON.stringify({
              origin: location.origin, pathname: location.pathname, title: document.title,
              inputs: [...document.querySelectorAll('input')].map(i => ({type:i.type,length:i.value.length})),
              authError: document.querySelector('form .text-rose-200')?.textContent,
              recovery: document.getElementById('cognis-startup-recovery')?.textContent?.slice(0, 600),
              configured: !!window.__cognisNative,
              receiver: !!window.__cognisNativeReceive,
              visibility: document.visibilityState,
              kinds: [...document.querySelectorAll('[data-kind]')].map(e => ({kind:e.dataset.kind,role:e.dataset.role,length:e.textContent.length})),
              bodyText: document.body.innerText.slice(-1600),
              composer: {present:!!document.querySelector('textarea'),disabled:document.querySelector('textarea')?.disabled,length:document.querySelector('textarea')?.value.length},
              sends: [...document.querySelectorAll('button')].filter(b => /Send|Queue/.test(b.getAttribute('aria-label') || '')).map(b => ({label:b.getAttribute('aria-label'),disabled:b.disabled})),
              failures: window.__m1StartupFailures
            })
            """)
        print("Bundled startup diagnostics: \(diagnostic ?? "unavailable")")
        throw URLError(.timedOut)
    }
}
