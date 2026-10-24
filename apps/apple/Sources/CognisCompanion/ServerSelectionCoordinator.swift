import AppKit
import CompanionContract

@MainActor
protocol ServerPrompting {
    func request(current: String?, appName: String) -> String?
    func invalidOrigin(appName: String)
}

@MainActor
struct NativeServerPrompt: ServerPrompting {
    func request(current: String?, appName: String) -> String? {
        let alert = NSAlert()
        alert.messageText = "Connect to " + appName
        alert.informativeText = "Enter your Cognis server origin. HTTPS is required except for local loopback HTTP. Switching servers isolates sign-in, cookies and offline storage."
        let input = NSTextField(frame: NSRect(x: 0, y: 0, width: 420, height: 26))
        input.stringValue = current ?? ""
        input.placeholderString = "https://your-cognis-server"
        alert.accessoryView = input
        alert.addButton(withTitle: "Connect")
        alert.addButton(withTitle: "Cancel")
        alert.window.initialFirstResponder = input
        NSApp.activate()
        return alert.runModal() == .alertFirstButtonReturn ? input.stringValue : nil
    }
    func invalidOrigin(appName: String) {
        let alert = NSAlert()
        alert.messageText = appName
        alert.informativeText = "Use an HTTPS origin without a path, credentials, query or fragment. Local HTTP must use localhost, 127.0.0.1 or ::1. No connection was opened."
        alert.alertStyle = .warning
        alert.runModal()
    }
}

/// Selection has no networking/authentication effects. Only a validated,
/// explicitly selected or same-flavor saved profile reaches the app's loader.
@MainActor
final class ServerSelectionCoordinator {
    let configuration: PackageConfiguration
    private let defaults: UserDefaults
    private let prompt: any ServerPrompting

    init(configuration: PackageConfiguration, defaults: UserDefaults,
         prompt: any ServerPrompting = NativeServerPrompt()) {
        self.configuration = configuration; self.defaults = defaults; self.prompt = prompt
    }
    func initialSelection(background: Bool) -> ServerProfile? {
        if let fixed = configuration.fixedProfile { return fixed }
        if let saved = defaults.string(forKey: "server"),
           let profile = try? configuration.profile(saved) { return profile }
        return background ? nil : select(current: nil)
    }
    func select(current: ServerProfile?) -> ServerProfile? {
        guard configuration.allowsServerSelection,
              let input = prompt.request(current: current?.origin.absoluteString,
                                         appName: configuration.displayName) else { return nil }
        do { return try configuration.profile(input) }
        catch { prompt.invalidOrigin(appName: configuration.displayName); return nil }
    }
    func remember(_ profile: ServerProfile) {
        defaults.set(profile.origin.absoluteString, forKey: "server")
    }
    func menuItem(target: AnyObject, action: Selector, key: String) -> NSMenuItem? {
        guard configuration.allowsServerSelection else { return nil }
        let item = NSMenuItem(title: "Change Server…", action: action, keyEquivalent: key)
        item.target = target
        item.isEnabled = true
        return item
    }
}
