import AppKit

/// Shared responder menus; application-specific actions remain owned by CompanionApp.
@MainActor
func applicationMenu(application: NSMenu) -> NSMenu {
    let menu = NSMenu()
    let root = NSMenuItem()
    root.submenu = application
    menu.addItem(root)
    let edit = NSMenuItem(title: "Edit", action: nil, keyEquivalent: "")
    edit.submenu = NSMenu(title: "Edit")
    for (title, action, key) in [
        ("Undo", Selector(("undo:")), "z"), ("Cut", #selector(NSText.cut(_:)), "x"),
        ("Copy", #selector(NSText.copy(_:)), "c"), ("Paste", #selector(NSText.paste(_:)), "v"),
        ("Select All", #selector(NSText.selectAll(_:)), "a")
    ] { edit.submenu?.addItem(withTitle: title, action: action, keyEquivalent: key) }
    menu.addItem(edit)
    let window = NSMenuItem(title: "Window", action: nil, keyEquivalent: "")
    window.submenu = NSMenu(title: "Window")
    window.submenu?.addItem(withTitle: "Close Window", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
    menu.addItem(window)
    return menu
}
