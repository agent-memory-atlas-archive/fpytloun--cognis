import AppKit
import CompanionContract

@MainActor
final class WindowSurface: NSView {
    let web: NSView
    let main: Bool
    let dragArea = TitlebarDragArea()
    init(web: NSView, main: Bool) {
        self.web = web; self.main = main
        super.init(frame: .zero)
        wantsLayer = true
        if !main { layer?.cornerRadius = 18; layer?.masksToBounds = true }
        addSubview(web)
        if main { addSubview(dragArea) }
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }
    override func layout() {
        super.layout()
        let inset: CGFloat = main && window?.styleMask.contains(.fullScreen) != true ? 38 : 0
        web.frame = NSRect(x: 0, y: 0, width: bounds.width, height: max(0, bounds.height - inset))
        dragArea.frame = NSRect(x: 0, y: bounds.height - inset, width: bounds.width, height: inset)
    }
}

@MainActor
final class TitlebarDragArea: NSView {
    override func mouseDown(with event: NSEvent) { window?.performDrag(with: event) }
}
