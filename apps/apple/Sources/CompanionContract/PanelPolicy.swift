import Foundation
import CoreGraphics

public func edgeRailFrames(visible: CGRect, count: Int, left: Bool, vertical: Double) -> [CGRect] {
    guard count > 0 else { return [] }
    let span = min(CGFloat(max(0, count - 1)) * 72 + 64, max(64, visible.height - 16))
    let ratio = vertical.isFinite ? min(max(vertical, 0), 1) : 0.5
    let y = visible.minY + 8 + CGFloat(ratio) * max(0, visible.height - span - 16)
    let x = left ? visible.minX + 8 : visible.maxX - 72
    return (0..<count).map { index in
        CGRect(x: x, y: y + CGFloat(index) * (count > 1 ? (span - 64) / CGFloat(count - 1) : 0),
               width: 64, height: 64)
    }
}

/// Pure event/geometry policy shared by the native windows and regression tests.
public struct AvatarGesture {
    public private(set) var dragging = false
    public init() {}
    public mutating func move(dx: CGFloat, dy: CGFloat) -> Bool {
        dragging = dragging || hypot(dx, dy) >= 5
        return dragging
    }
    public var shouldClick: Bool { !dragging }
}

public func confinedFrame(_ frame: CGRect, to visible: CGRect) -> CGRect {
    let width = min(frame.width, visible.width), height = min(frame.height, visible.height)
    return CGRect(x: min(max(frame.minX, visible.minX), visible.maxX - width),
                  y: min(max(frame.minY, visible.minY), visible.maxY - height),
                  width: width, height: height)
}

public func anchoredFrame(icon: CGRect, size: CGSize, visible: CGRect) -> CGRect {
    let right = icon.maxX + 10
    let x = right + size.width <= visible.maxX ? right : icon.minX - size.width - 10
    return confinedFrame(CGRect(x: x, y: icon.midY - size.height / 2,
                               width: size.width, height: size.height), to: visible)
}

public func shouldDismissPanel(outside: Bool, ownedInteraction: Bool) -> Bool {
    outside && !ownedInteraction
}
