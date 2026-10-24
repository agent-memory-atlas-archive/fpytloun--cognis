import XCTest
import CoreGraphics
@testable import CompanionContract

final class PanelPolicyTests: XCTestCase {
    func testRailNeverDetachesFromEitherWorkAreaEdge() {
        for area in [CGRect(x: 0, y: 24, width: 1440, height: 850),
                     CGRect(x: -1200, y: 40, width: 1200, height: 600)] {
            for left in [true, false] {
                for position in [-100.0, 0, 0.5, 1, 100, .nan] {
                    let frames = edgeRailFrames(visible: area, count: 3, left: left, vertical: position)
                    for frame in frames {
                        XCTAssertEqual(frame.minX, left ? area.minX + 8 : area.maxX - 72)
                        XCTAssertTrue(area.contains(frame))
                    }
                }
            }
        }
    }
    func testClickVersusDragThresholdIsSticky() {
        var gesture = AvatarGesture()
        XCTAssertTrue(gesture.shouldClick)
        XCTAssertFalse(gesture.move(dx: 2, dy: 2))
        XCTAssertTrue(gesture.shouldClick)
        XCTAssertTrue(gesture.move(dx: 3, dy: 4))
        XCTAssertFalse(gesture.shouldClick)
        XCTAssertTrue(gesture.move(dx: 0, dy: 0))
        XCTAssertFalse(gesture.shouldClick)
    }

    func testAnchoringAndRecoveryWithDifferentWorkAreas() {
        let display = CGRect(x: -1200, y: 24, width: 1200, height: 760)
        let icon = CGRect(x: -70, y: 30, width: 64, height: 64)
        let anchored = anchoredFrame(icon: icon, size: CGSize(width: 450, height: 640), visible: display)
        XCTAssertTrue(display.contains(anchored))
        XCTAssertLessThan(anchored.maxX, icon.minX)
        let removedDisplay = CGRect(x: 0, y: 40, width: 800, height: 500)
        let restored = confinedFrame(anchored, to: removedDisplay)
        XCTAssertTrue(removedDisplay.contains(restored))
        XCTAssertEqual(restored.height, 500)
    }

    func testOwnedInteractionsNeverDismiss() {
        XCTAssertTrue(shouldDismissPanel(outside: true, ownedInteraction: false))
        XCTAssertFalse(shouldDismissPanel(outside: false, ownedInteraction: false))
        XCTAssertFalse(shouldDismissPanel(outside: true, ownedInteraction: true))
        XCTAssertFalse(shouldDismissPanel(outside: false, ownedInteraction: true))
    }
}
