import AppKit
import Sparkle
import CompanionContract

@MainActor
protocol UpdateDriving: AnyObject {
    var canCheck: Bool { get }
    var automaticChecks: Bool { get set }
    var automaticInstall: Bool { get set }
    func start() throws
    func check()
}

/// Thin standard Sparkle API adapter, not an alternate downloader/installer.
@MainActor
private final class SparkleUpdateDriver: UpdateDriving {
    let controller: SPUStandardUpdaterController
    init(delegate: any SPUUpdaterDelegate) {
        controller = SPUStandardUpdaterController(startingUpdater: false, updaterDelegate: delegate, userDriverDelegate: nil)
    }
    var canCheck: Bool { controller.updater.canCheckForUpdates }
    var automaticChecks: Bool {
        get { controller.updater.automaticallyChecksForUpdates }
        set { controller.updater.automaticallyChecksForUpdates = newValue }
    }
    var automaticInstall: Bool {
        get { controller.updater.automaticallyDownloadsUpdates }
        set { controller.updater.automaticallyDownloadsUpdates = newValue }
    }
    func start() throws { try controller.updater.start() }
    func check() { controller.checkForUpdates(nil) }
}

/// App-global lifecycle; never recreated on server/profile changes.
@MainActor
final class UpdateCoordinator: NSObject, SPUUpdaterDelegate {
    private var driver: (any UpdateDriving)?
    private let feed: String?
    let availability: UpdateAvailability
    private(set) var status: String

    init(info: [String: Any] = Bundle.main.infoDictionary ?? [:],
         makeDriver: @MainActor (any SPUUpdaterDelegate) -> any UpdateDriving = { SparkleUpdateDriver(delegate: $0) }) {
        availability = UpdateAvailability(info: info)
        feed = info["SUFeedURL"] as? String
        switch availability {
        case .available: status = "Publisher updates"
        case .managed: status = "Updates managed by Homebrew"
        case .unavailable: status = "Updates unavailable: publisher configuration missing"
        }
        super.init()
        if availability == .available {
            let driver = makeDriver(self)
            self.driver = driver
            do { try driver.start() }
            catch { self.driver = nil; status = "Updates unavailable: publisher configuration invalid" }
        }
    }
    func menu() -> NSMenu {
        let menu = NSMenu(title: "Updates")
        menu.autoenablesItems = false
        menu.addItem(withTitle: status, action: nil, keyEquivalent: "").isEnabled = false
        let check = menu.addItem(withTitle: "Check Now…", action: #selector(checkNow), keyEquivalent: "")
        check.target = self; check.isEnabled = driver?.canCheck == true
        for (title, selector, enabled) in [
            ("Automatically Check for Updates", #selector(toggleChecks), driver?.automaticChecks == true),
            ("Automatically Download and Install on Quit", #selector(toggleInstall), driver?.automaticInstall == true)
        ] {
            let item = menu.addItem(withTitle: title, action: selector, keyEquivalent: "")
            item.target = self; item.isEnabled = driver != nil; item.state = enabled ? .on : .off
        }
        return menu
    }
    @objc private func checkNow() { if driver?.canCheck == true { driver?.check() } }
    @objc private func toggleChecks(_ sender: NSMenuItem) {
        driver?.automaticChecks.toggle()
        sender.state = driver?.automaticChecks == true ? .on : .off
    }
    @objc private func toggleInstall(_ sender: NSMenuItem) {
        driver?.automaticInstall.toggle()
        sender.state = driver?.automaticInstall == true ? .on : .off
    }
    // Pin the bundle's publisher feed even if Sparkle's local defaults contain a URL.
    func feedURLString(for updater: SPUUpdater) -> String? { feed }
    // Never invoke the immediate install block. Sparkle installs after ordinary quit.
    func updater(_ updater: SPUUpdater, willInstallUpdateOnQuit item: SUAppcastItem,
                 immediateInstallationBlock immediateInstallHandler: @escaping () -> Void) -> Bool { true }
    func updater(_ updater: SPUUpdater, shouldPostponeRelaunchForUpdate item: SUAppcastItem,
                 untilInvokingBlock installHandler: @escaping () -> Void) -> Bool { true }
    func updaterShouldRelaunchApplication(_ updater: SPUUpdater) -> Bool { false }
    func updaterShouldPromptForPermissionToCheck(forUpdates updater: SPUUpdater) -> Bool { false }
}
