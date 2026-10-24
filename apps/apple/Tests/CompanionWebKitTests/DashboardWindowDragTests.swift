import XCTest
import AppKit
import WebKit
import CompanionContract
@testable import CognisCompanion

/// Actual WK/AppKit input into a test-only full Apple export, never an installed app.
@MainActor
final class DashboardWindowDragTests: XCTestCase {
    private func evaluate(_ host: BundleWebView, _ script: String) async throws -> Any? {
        try await host.web.callAsyncJavaScript(script, arguments: [:], in: nil, contentWorld: .page)
    }
    private func click(_ host: BundleWebView, _ id: String) async throws {
        _ = try await host.web.callAsyncJavaScript("document.getElementById(id).click();",
            arguments: ["id": id], in: nil, contentWorld: .page)
    }
    private func snapshot(_ host: BundleWebView) async throws -> [String: Any] {
        try await click(host, "native-drag-observe")
        let raw = try await evaluate(host, "return document.getElementById('native-drag-snapshot').textContent;") as? String ?? ""
        return try XCTUnwrap(JSONSerialization.jsonObject(with: Data(raw.utf8)) as? [String: Any])
    }
    private func wait(_ host: BundleWebView, seconds: Double, condition: String) async throws {
        let deadline = ProcessInfo.processInfo.systemUptime + seconds
        repeat {
            if try await evaluate(host, "return Boolean(\(condition));") as? Bool == true { return }
            try await Task.sleep(for: .milliseconds(20))
        } while ProcessInfo.processInfo.systemUptime < deadline
        let bootstrap = try await evaluate(host, "return document.getElementById('native-drag-bootstrap')?.textContent;")
        XCTFail("Native drag readiness failed: \(condition); bootstrap=\(bootstrap ?? "missing")")
        throw NSError(domain: "DashboardWindowDrag", code: 1)
    }
    private func point(_ host: BundleWebView, selector: String) async throws -> NSPoint {
        let raw = try await host.web.callAsyncJavaScript("""
            const element = document.querySelector(selector);
            element.scrollIntoView({block:'nearest',inline:'nearest'});
            const r = element.getBoundingClientRect();
            return {x:r.x + Math.min(100,r.width/2),y:r.y+r.height/2};
            """, arguments: ["selector": selector], in: nil, contentWorld: .page)
        let value = try XCTUnwrap(raw as? [String: Double])
        return NSPoint(x: value["x"]!, y: value["y"]!)
    }
    private func target(_ host: BundleWebView, _ dom: NSPoint) throws -> NSView {
        let local = NSPoint(x: dom.x, y: host.web.isFlipped ? dom.y : host.web.bounds.height - dom.y)
        return try XCTUnwrap(host.web.hitTest(local))
    }
    private func event(_ host: BundleWebView, window: NSWindow,
                       type: NSEvent.EventType, dom: NSPoint, number: Int) throws -> NSEvent {
        let local = NSPoint(x: dom.x, y: host.web.isFlipped ? dom.y : host.web.bounds.height - dom.y)
        return try XCTUnwrap(NSEvent.mouseEvent(with: type,
            location: host.web.convert(local, to: nil), modifierFlags: [],
            timestamp: ProcessInfo.processInfo.systemUptime, windowNumber: window.windowNumber,
            context: nil, eventNumber: number, clickCount: 1, pressure: type == .leftMouseUp ? 0 : 1))
    }
    private func assertPreserved(_ state: [String: Any], phase: String) throws {
        let preserved = try XCTUnwrap(state["preserved"] as? [String: Any])
        for key in ["viewport", "expanded", "draft", "focus", "scroll"] {
            XCTAssertEqual(preserved[key] as? Bool, true, "\(phase): \(key)")
        }
        XCTAssertEqual(preserved["selection"] as? [Int], [2, 7], phase)
    }

    func testOnePopulatedNativeDashboardGesture() async throws { try await run(count: 1, streaming: false) }
    func testFivePopulatedNativeDashboardGestureWithStream() async throws { try await run(count: 5, streaming: true) }

    private func run(count: Int, streaming: Bool) async throws {
        guard let path = ProcessInfo.processInfo.environment["COGNIS_WINDOW_DRAG_WEB_ROOT"],
              FileManager.default.fileExists(atPath: path + "/WINDOW_DRAG_ACCEPTANCE_ONLY") else {
            throw XCTSkip("Build test-only full Apple export with build-window-drag-native.mjs")
        }
        _ = NSApplication.shared
        let root = URL(fileURLWithPath: path)
        let profile = try ServerProfile("https://window-drag.acceptance.invalid",
            storageNamespace: "cz.fpy.cognis.tests.window-drag." + UUID().uuidString)
        let host = try BundleWebView(profile: profile, root: root, surface: "main")
        let services = try String(contentsOf: root.appendingPathComponent("window-drag-services.js"), encoding: .utf8)
        host.web.configuration.userContentController.addUserScript(WKUserScript(
            source: services, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1540, height: 980),
            styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.contentView = host.web
        defer { host.invalidate(); window.contentView = nil; window.close() }
        XCTAssertTrue(host.web.window === window)
        XCTAssertGreaterThan(host.web.bounds.width, 0)
        host.start(path: "/dashboard-drag-acceptance?windows=\(count)&streaming=\(streaming ? 1 : 0)")
        try await wait(host, seconds: 15, condition: """
            (() => { const s=JSON.parse(document.getElementById('native-drag-bootstrap')?.textContent || '{}');
              return s.auth === 'authenticated' && !!s.owner && s.native === true && s.surface === 'main'; })()
            """)
        try await click(host, "native-drag-seed")
        // Same five-second message-119 readiness AFTER auth/bootstrap, no fake ready.
        try await wait(host, seconds: 5, condition: """
            (() => {
              const state = JSON.parse(document.querySelector('#native-drag-bootstrap').textContent);
              return state.summaryReady && state.initialLoaded.length === \(count)
                && !!document.querySelector('[data-testid="workspace-dock"]')
                && [...document.querySelectorAll('[data-kind="message"]')]
                  .filter(node => node.textContent.includes('Synthetic message 119')).length === \(count);
            })()
            """)
        let key = "conversation:drag-chat-\(count - 1)"
        _ = try await host.web.callAsyncJavaScript("""
            const panel=document.querySelector('[data-window-key="'+key+'"]');
            panel.querySelectorAll('[data-kind="activity_segment"] > button[aria-expanded="false"],[data-kind="tool_group"] > button[aria-expanded="false"]')
              .forEach(button => button.click());
            """, arguments: ["key": key], in: nil, contentWorld: .page)
        let detailSelector = "button[aria-controls=\"tool-call-content-drag-chat-\(count - 1)-detail\"]"
        let detail = try await point(host, selector: detailSelector)
        let detailTarget = try target(host, detail)
        detailTarget.mouseDown(with: try event(host, window: window, type: .leftMouseDown, dom: detail, number: 1))
        detailTarget.mouseUp(with: try event(host, window: window, type: .leftMouseUp, dom: detail, number: 2))
        try await wait(host, seconds: 5, condition: """
            document.querySelector('button[aria-controls="tool-call-content-drag-chat-\(count - 1)-detail"]')?.getAttribute('aria-expanded') === 'true'
            """)
        if streaming {
            try await wait(host, seconds: 5, condition: "document.body.textContent.includes('Native streaming token ')")
        }
        try await click(host, "native-drag-prepare")
        let prepared = try await snapshot(host)
        try assertPreserved(prepared, phase: "focused")
        XCTAssertEqual(prepared["summaryReady"] as? Bool, true)
        XCTAssertEqual(prepared["dock"] as? Bool, true)
        XCTAssertEqual((prepared["initialLoaded"] as? [String])?.count, count)
        let initialVisual = try XCTUnwrap(prepared["visual"] as? [String: Double])
        let streamBefore = (prepared["stream"] as? String).flatMap(Int.init)
        if streaming {
            XCTAssertNotNil(streamBefore, "Streaming must already render before pointerdown")
        }
        let origin = try await point(host, selector: "[data-testid=\"workspace-window-drag-\(key)\"]")
        let input = try target(host, origin)
        input.mouseDown(with: try event(host, window: window, type: .leftMouseDown, dom: origin, number: 3))
        // Wait one rendered frame through public DOM, not a fabricated callback.
        _ = try await evaluate(host, "await new Promise(requestAnimationFrame);")
        let start = try await snapshot(host)
        try assertPreserved(start, phase: "start")
        try await click(host, "native-drag-reset")
        var motionEvidence: [[String: Any]] = []
        var last = origin
        for index in 1...24 {
            last = NSPoint(x: origin.x + Double(index * 2), y: origin.y + Double(index))
            input.mouseDragged(with: try event(host, window: window, type: .leftMouseDragged, dom: last, number: index + 3))
            _ = try await evaluate(host, "await new Promise(requestAnimationFrame);")
            if index == 12 || index == 24 {
                let moving = try await snapshot(host)
                motionEvidence.append(moving)
                try assertPreserved(moving, phase: "motion-\(index)")
                XCTAssertEqual(moving["publications"] as? Int, 0)
                XCTAssertEqual(moving["derivedLayoutWriteAttempts"] as? Int, 0)
                XCTAssertEqual(moving["physicalWorkspaceWrites"] as? Int, 0)
                let visual = try XCTUnwrap(moving["visual"] as? [String: Double])
                XCTAssertEqual(try XCTUnwrap(visual["x"]), try XCTUnwrap(initialVisual["x"]) + Double(index * 2), accuracy: 1)
                XCTAssertEqual(try XCTUnwrap(visual["y"]), try XCTUnwrap(initialVisual["y"]) + Double(index), accuracy: 1)
                if streaming && index == 24 {
                    let token = try XCTUnwrap((moving["stream"] as? String).flatMap(Int.init))
                    XCTAssertGreaterThan(token, try XCTUnwrap(streamBefore), "Stream must advance during native motion")
                }
            }
        }
        input.mouseUp(with: try event(host, window: window, type: .leftMouseUp, dom: last, number: 28))
        _ = try await evaluate(host, "await new Promise(requestAnimationFrame);")
        let final = try await snapshot(host)
        try assertPreserved(final, phase: "commit")
        XCTAssertEqual(final["publications"] as? Int, 1)
        XCTAssertEqual(final["derivedLayoutWriteAttempts"] as? Int, 1)
        XCTAssertEqual(final["physicalWorkspaceWrites"] as? Int, 2)
        XCTAssertEqual(final["native"] as? Bool, true)
        XCTAssertEqual(final["surface"] as? String, "main")
        XCTAssertEqual(final["readyRows"] as? Int, count)
        let finalVisual = try XCTUnwrap(final["visual"] as? [String: Double])
        let committed = try XCTUnwrap(final["geometry"] as? [[String: Any]])
        let committedRect = try XCTUnwrap(committed.first(where: { $0["key"] as? String == key })?["rect"] as? [String: Double])
        XCTAssertEqual(try XCTUnwrap(finalVisual["x"]), try XCTUnwrap(initialVisual["x"]) + 48, accuracy: 1)
        XCTAssertEqual(try XCTUnwrap(finalVisual["y"]), try XCTUnwrap(initialVisual["y"]) + 24, accuracy: 1)
        XCTAssertEqual(try XCTUnwrap(finalVisual["x"]), try XCTUnwrap(committedRect["x"]), accuracy: 1)
        XCTAssertEqual(try XCTUnwrap(finalVisual["y"]), try XCTUnwrap(committedRect["y"]), accuracy: 1)
        if streaming { XCTAssertNotNil(final["stream"] as? String) }
        let evidence: [String: Any] = ["count": count, "streaming": streaming,
            "prepared": prepared, "focusAndStart": start, "motion": motionEvidence, "final": final,
            "startPublicationDelta": (start["publications"] as? Int ?? 0) - (prepared["publications"] as? Int ?? 0),
            "startPhysicalWriteDelta": (start["physicalWorkspaceWrites"] as? Int ?? 0) - (prepared["physicalWorkspaceWrites"] as? Int ?? 0)]
        let attachment = XCTAttachment(data: try JSONSerialization.data(withJSONObject: evidence, options: [.sortedKeys]),
            uniformTypeIdentifier: "public.json")
        attachment.name = "native-dashboard-drag-\(count)"
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
