import AppKit
import WebKit
import XCTest
@testable import CognisCompanion

@MainActor
final class RailInputTests: XCTestCase {
    func testOriginalScreenAnchorDoesNotAccumulateMovingWindowFeedbackOrBackingScale() {
        // Cocoa locations and frames both use screen points, not CSS/client or backing pixels.
        XCTAssertEqual(CompanionApp.railDragY(frameY: 100, pointerStartY: 500, currentPointerY: 510), 110)
        XCTAssertEqual(CompanionApp.railDragY(frameY: 100, pointerStartY: 500, currentPointerY: 520), 120)
        XCTAssertEqual(CompanionApp.railDragY(frameY: 100, pointerStartY: 500, currentPointerY: 495), 95)
    }
    func testRailAcceptsFirstMouseAndTracksInactiveEnterExit() throws {
        let view = RailWebView(frame: NSRect(x: 0, y: 0, width: 64, height: 200), configuration: WKWebViewConfiguration())
        let window = DesktopPanel(contentRect: view.frame, styleMask: [.borderless, .nonactivatingPanel],
                                  backing: .buffered, defer: false)
        window.contentView = view
        window.isReleasedWhenClosed = false
        defer { window.contentView = nil; window.close() }
        let down = try XCTUnwrap(NSEvent.mouseEvent(with: .leftMouseDown, location: NSPoint(x: 50, y: 50),
            modifierFlags: [], timestamp: 1, windowNumber: window.windowNumber,
            context: nil, eventNumber: 1, clickCount: 1, pressure: 1))
        XCTAssertTrue(view.acceptsFirstMouse(for: down))
        view.updateTrackingAreas()
        XCTAssertTrue(view.trackingAreas.contains { $0.options.contains(.activeAlways) })
        var observed = 0
        view.onPointerChange = { observed += 1 }
        for type in [NSEvent.EventType.mouseEntered, .mouseExited] {
            let event = try XCTUnwrap(NSEvent.enterExitEvent(with: type, location: NSPoint(x: 50, y: 50),
                modifierFlags: [], timestamp: 2, windowNumber: window.windowNumber,
                context: nil, eventNumber: 2, trackingNumber: 1, userData: nil))
            if type == .mouseEntered { view.mouseEntered(with: event) } else { view.mouseExited(with: event) }
        }
        XCTAssertEqual(observed, 2)
    }
}
