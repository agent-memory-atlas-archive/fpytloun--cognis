// Task acceptance helper. Requires existing Accessibility permission; never requests it.
import AppKit
import ApplicationServices

func attribute(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success else { return nil }
    return value
}
func text(_ element: AXUIElement, _ name: String) -> String {
    attribute(element, name) as? String ?? ""
}
func children(_ element: AXUIElement) -> [AXUIElement] {
    let children = attribute(element, kAXChildrenAttribute) as? [AXUIElement] ?? []
    let windows = attribute(element, kAXWindowsAttribute) as? [AXUIElement] ?? []
    return windows + children
}
var visited: [AXUIElement] = []
func walk(_ element: AXUIElement, depth: Int = 0) -> [AXUIElement] {
    guard depth < 25, !visited.contains(where: { CFEqual($0, element) }) else { return [] }
    visited.append(element)
    return [element] + children(element).filter {
        // Do not enumerate system Apple-menu recent documents.
        text($0, kAXTitleAttribute) != "Apple"
    }.flatMap { walk($0, depth: depth + 1) }
}
guard AXIsProcessTrusted() else {
    fputs("BLOCKED: no existing Accessibility permission.\n", stderr); exit(2)
}
let acceptance = ProcessInfo.processInfo.environment["COGNIS_AX_ACCEPTANCE"] == "1"
let identifier = "cz.fpy.cognis.companion" + (acceptance ? ".acceptance" : "")
let checkout = ProcessInfo.processInfo.environment["COGNIS_AX_CURRENT"] == "1"
    ? "/cognis-macos-companion-m1-current/"
    : acceptance ? "/cognis-macos-companion-m1-acceptance/" : "/cognis-macos-companion-m1/"
guard let app = NSRunningApplication.runningApplications(withBundleIdentifier: identifier)
    .first(where: { $0.executableURL?.path.contains(checkout) == true }) else {
    fputs("Task app not running.\n", stderr); exit(2)
}
let root = AXUIElementCreateApplication(app.processIdentifier)
let command = CommandLine.arguments.dropFirst().first ?? "dump"
let elements = walk(root)
switch command {
case "activate":
    app.activate()
case "close-main":
    guard let window = elements.first(where: {
        text($0, kAXRoleAttribute) == kAXWindowRole && text($0, kAXTitleAttribute) == "Cognis"
    }), let close = attribute(window, kAXCloseButtonAttribute) else { exit(3) }
    guard AXUIElementPerformAction(unsafeBitCast(close, to: AXUIElement.self),
                                  kAXPressAction as CFString) == .success else { exit(3) }
case "escape":
    guard app.activate() else { exit(3) }
    for down in [true, false] {
        CGEvent(keyboardEventSource: nil, virtualKey: 53, keyDown: down)?.post(tap: .cghidEventTap)
    }
case "assert-draft":
    guard CommandLine.arguments.count == 3,
          let element = elements.first(where: {
              text($0, kAXRoleAttribute) == kAXTextAreaRole
                  && text($0, kAXDescriptionAttribute) == "Chat message"
          }), text(element, kAXValueAttribute) == CommandLine.arguments[2] else { exit(3) }
    print("Native composer draft matches expected acceptance text.")
case "dump":
    for (index, element) in elements.enumerated() {
        // Never print field values: the app may have a password form.
        let role = text(element, kAXRoleAttribute)
        let title = text(element, kAXTitleAttribute)
        let description = text(element, kAXDescriptionAttribute)
        let visibleText = role == kAXStaticTextRole ? String(text(element, kAXValueAttribute).prefix(500)) : ""
        print("\(index) \(role) \(title) \(description) \(visibleText)")
    }
case "press", "set":
    guard CommandLine.arguments.count >= 3, let index = Int(CommandLine.arguments[2]),
          elements.indices.contains(index) else { exit(2) }
    let element = elements[index]
    if command == "press" {
        guard AXUIElementPerformAction(element, kAXPressAction as CFString) == .success else { exit(3) }
    } else {
        guard CommandLine.arguments.count == 4 else { exit(2) }
        guard AXUIElementSetAttributeValue(element, kAXValueAttribute as CFString,
                                          CommandLine.arguments[3] as CFString) == .success else { exit(3) }
    }
case "press-label", "fill-label", "press-menu":
    guard CommandLine.arguments.count >= 3 else { exit(2) }
    let label = CommandLine.arguments[2]
    let roles = command == "fill-label" ? [kAXTextFieldRole, kAXTextAreaRole]
        : command == "press-menu" ? [kAXMenuItemRole] : [kAXButtonRole]
    guard let element = elements.first(where: {
        roles.contains(text($0, kAXRoleAttribute))
            && [text($0, kAXTitleAttribute), text($0, kAXDescriptionAttribute)].contains(label)
    }) else { exit(3) }
    if command != "fill-label" {
        guard AXUIElementPerformAction(element, kAXPressAction as CFString) == .success else { exit(3) }
    } else {
        guard CommandLine.arguments.count == 4, app.activate(),
              AXUIElementSetAttributeValue(element, kAXFocusedAttribute as CFString, kCFBooleanTrue) == .success
        else { exit(3) }
        for down in [true, false] {
            let event = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: down)
            event?.flags = .maskCommand
            event?.post(tap: .cghidEventTap)
        }
        let characters = Array(CommandLine.arguments[3].utf16)
        guard characters.count <= 1000 else { exit(2) }
        for down in [true, false] {
            let event = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: down)
            characters.withUnsafeBufferPointer {
                event?.keyboardSetUnicodeString(stringLength: $0.count, unicodeString: $0.baseAddress!)
            }
            event?.post(tap: .cghidEventTap)
        }
    }
default: exit(2)
}
