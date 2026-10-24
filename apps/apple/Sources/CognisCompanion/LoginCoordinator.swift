import AppKit
import ServiceManagement
import Carbon
import CompanionContract

@MainActor
protocol LoginServiceAdapting {
    var status: LoginRegistrationStatus { get }
    func register() throws
    func unregister() async throws
}

@MainActor
struct SystemLoginService: LoginServiceAdapting {
    var status: LoginRegistrationStatus {
        switch SMAppService.mainApp.status {
        case .enabled: return .enabled
        case .notRegistered: return .notRegistered
        case .requiresApproval: return .requiresApproval
        case .notFound: return .notFound
        @unknown default: return .notFound
        }
    }
    func register() throws { try SMAppService.mainApp.register() }
    func unregister() async throws { try await SMAppService.mainApp.unregister() }
}

/// Reads actual system status. Never registers from init/launch or a saved boolean.
@MainActor
final class LoginCoordinator: NSObject, NSMenuDelegate {
    private let service: any LoginServiceAdapting
    private let defaults: UserDefaults
    private(set) var error: String?
    private var busy = false
    var onChange: (() -> Void)?

    init(service: any LoginServiceAdapting = SystemLoginService(), defaults: UserDefaults = .standard) {
        self.service = service; self.defaults = defaults
    }
    var startInBackground: Bool { defaults.bool(forKey: "startInBackground") }
    var status: LoginRegistrationStatus { service.status }
    static var launchedAtLogin: Bool {
        let event = NSAppleEventManager.shared().currentAppleEvent
        return event?.eventID == kAEOpenApplication
            && event?.paramDescriptor(forKeyword: keyAEPropData)?.enumCodeValue == keyAELaunchedAsLogInItem
    }
    var explanation: String {
        if let error { return error }
        switch service.status {
        case .enabled: return "Enabled by macOS"
        case .notRegistered: return "Not registered (opt-in)"
        case .requiresApproval: return "Approval required in System Settings > General > Login Items"
        case .notFound: return "App unavailable for registration; use an installed signed app and retry"
        }
    }
    func menu() -> NSMenu {
        let menu = NSMenu(title: "Startup")
        menu.delegate = self; menu.autoenablesItems = false
        populate(menu)
        return menu
    }
    func menuWillOpen(_ menu: NSMenu) { populate(menu) }
    private func populate(_ menu: NSMenu) {
        menu.removeAllItems()
        menu.addItem(withTitle: explanation, action: nil, keyEquivalent: "")
        let login = menu.addItem(withTitle: "Launch at Login", action: #selector(toggleLogin), keyEquivalent: "")
        login.target = self
        login.state = service.status == .enabled ? .on : service.status == .requiresApproval ? .mixed : .off
        login.isEnabled = !busy && service.status != .notFound
        let background = menu.addItem(withTitle: "Start in Background", action: #selector(toggleBackground), keyEquivalent: "")
        background.target = self; background.state = startInBackground ? .on : .off
    }
    @objc private func toggleBackground(_ item: NSMenuItem) {
        defaults.set(!startInBackground, forKey: "startInBackground")
        item.state = startInBackground ? .on : .off
    }
    @objc private func toggleLogin() { Task { await setEnabled(service.status == .notRegistered) } }
    func setEnabled(_ enabled: Bool) async {
        guard !busy else { return }
        busy = true; error = nil
        defer { busy = false; onChange?() }
        do {
            if enabled { try service.register() }
            else { try await service.unregister() }
        } catch {
            self.error = "Login registration failed; check the installed app and macOS Login Items"
        }
    }
}
