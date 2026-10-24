import AppKit

/// Client-local controls. Callbacks retain the existing management owners.
@MainActor
final class NativeSettingsWindow: NSWindowController {
    init(railVisible: Bool, left: Bool, previews: Bool,
         rail: @escaping () -> Void, side: @escaping (Bool) -> Void,
         tuck: @escaping () -> Void, preview: @escaping () -> Void,
         notifications: @escaping () -> Void, startup: NSMenu) {
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 440, height: 390),
            styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "Settings"
        window.isReleasedWhenClosed = false
        super.init(window: window)
        let stack = NSStackView()
        stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 12
        stack.edgeInsets = NSEdgeInsets(top: 24, left: 24, bottom: 24, right: 24)
        func heading(_ text: String) {
            let label = NSTextField(labelWithString: text)
            label.font = .boldSystemFont(ofSize: 13); stack.addArrangedSubview(label)
        }
        func button(_ title: String, checked: Bool? = nil, action: @escaping () -> Void) {
            let control = SettingsButton(title: title, checked: checked, action: action)
            stack.addArrangedSubview(control)
        }
        heading("Rail / Display")
        button("Show desktop chats", checked: railVisible, action: rail)
        button("Dock avatars on the left", checked: left) { side(true) }
        button("Dock avatars on the right", checked: !left) { side(false) }
        button("Toggle half-hide avatars", action: tuck)
        heading("Notifications")
        button("Show reply previews", checked: previews, action: preview)
        button("macOS notification controls…", action: notifications)
        heading("Startup")
        button("Startup options…") { startup.popUp(positioning: nil, at: NSEvent.mouseLocation, in: nil) }
        let note = NSTextField(wrappingLabelWithString:
            "These controls apply only to this Mac. Half-hide is saved by the main web workspace. macOS controls notification visibility.")
        note.textColor = .secondaryLabelColor; stack.addArrangedSubview(note)
        window.contentView = stack
        window.center()
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }
}

@MainActor
private final class SettingsButton: NSButton {
    private let run: () -> Void
    init(title: String, checked: Bool?, action: @escaping () -> Void) {
        run = action
        super.init(frame: .zero)
        self.title = title; target = self; self.action = #selector(invoke)
        if let checked { setButtonType(.switch); state = checked ? .on : .off }
        else { bezelStyle = .rounded }
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }
    @objc private func invoke() { run() }
}
