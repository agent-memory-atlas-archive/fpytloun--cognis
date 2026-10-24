import AppKit
import CompanionContract
import Darwin

struct LocalProcessResult: Sendable {
    let code: Int32
    let data: Data
}

protocol LocalProcessRunning: Sendable {
    func run(binary: URL, arguments: [String]) throws -> LocalProcessResult
}

@MainActor
final class LocalExecutorAdapter: NSObject {
    private let runner: any LocalProcessRunning
    private let discover: @MainActor () -> URL?
    private var observation: ExecutorObservation?
    private var busy = false
    private var status = "Not inspected"
    var onChange: (() -> Void)?

    init(runner: any LocalProcessRunning = BoundedLocalProcess(),
         discover: @escaping @MainActor () -> URL? = LocalExecutorAdapter.installedBinary) {
        self.runner = runner; self.discover = discover
    }

    static func installedBinary() -> URL? {
        for prefix in ["/opt/homebrew", "/usr/local"] {
            let binary = URL(fileURLWithPath: prefix + "/bin/cognis-executor")
            let target = binary.resolvingSymlinksInPath()
            guard target.path.hasPrefix(prefix + "/Cellar/cognis-executor/"),
                  FileManager.default.isExecutableFile(atPath: binary.path),
                  let attributes = try? FileManager.default.attributesOfItem(atPath: target.path),
                  let owner = attributes[.ownerAccountID] as? NSNumber,
                  owner.uint32Value == getuid() || owner.uint32Value == 0,
                  let mode = attributes[.posixPermissions] as? NSNumber,
                  mode.intValue & 0o022 == 0 else { continue }
            // Resolve the installed keg's receipt, not a same-named formula in
            // another tap. Never install/tap/upgrade to repair discovery.
            let keg = target.deletingLastPathComponent().deletingLastPathComponent()
            guard let data = try? Data(contentsOf: keg.appendingPathComponent("INSTALL_RECEIPT.json")),
                  let receipt = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let source = receipt["source"] as? [String: Any],
                  source["tap"] as? String == "fpytloun/tap" else { continue }
            let brew = URL(fileURLWithPath: prefix + "/bin/brew")
            guard FileManager.default.isExecutableFile(atPath: brew.path) else { continue }
            return brew
        }
        return nil
    }

    func menu() -> NSMenu {
        let menu = NSMenu(title: "Local Executor")
        menu.autoenablesItems = false
        menu.addItem(withTitle: busy ? "Operation pending" : status, action: nil, keyEquivalent: "").isEnabled = false
        menu.addItem(withTitle: "Controller connection: not verified", action: nil, keyEquivalent: "").isEnabled = false
        for action in ExecutorAction.allCases {
            let item = menu.addItem(withTitle: action == .status ? "Refresh Status" : action == .logs ? "Safe Service Summary…" : action.rawValue.capitalized,
                                    action: #selector(selected(_:)), keyEquivalent: "")
            item.target = self; item.representedObject = action.rawValue
            item.isEnabled = !busy && (action == .status || observation?.owned == true && observation?.ok == true)
        }
        return menu
    }
    @objc private func selected(_ sender: NSMenuItem) {
        guard let raw = sender.representedObject as? String, let action = ExecutorAction(rawValue: raw) else { return }
        Task { await perform(action) }
    }
    func perform(_ action: ExecutorAction) async {
        guard !busy else { return }
        guard action == .status || observation?.owned == true && observation?.ok == true else { return }
        guard let binary = discover() else {
            observation = nil; status = "Existing Homebrew executor not installed"; onChange?(); return
        }
        busy = true; onChange?()
        let runner = runner
            let result: LocalProcessResult? = await Task.detached {
                do {
                    let outcome = try runner.run(binary: binary, arguments: action.arguments)
                    if action == .status || action == .logs { return outcome }
                    // Mutation output is prose and is never used as status.
                    guard outcome.code == 0 else { return outcome }
                    return try runner.run(binary: binary, arguments: ExecutorAction.status.arguments)
                } catch { return nil }
            }.value
            self.busy = false
            let prefix = binary.deletingLastPathComponent().deletingLastPathComponent().path
            if let result, result.code == 0,
               let value = try? ExecutorObservation.homebrew(result.data, prefix: prefix, user: NSUserName()) {
                self.observation = value
                self.status = value.state + (value.ok ? "" : " — " + value.code)
                if action == .logs {
                    let alert = NSAlert()
                    alert.messageText = "Executor service summary"
                    alert.informativeText = (value.preview ?? ["Unavailable"]).joined(separator: "\n")
                        + "\nFree-form logs are withheld to protect credentials and content."
                    alert.runModal()
                }
            } else {
                self.observation = nil
                self.status = result == nil
                    ? "Operation outcome unknown; refresh status before any retry"
                    : "Homebrew service status could not be verified; refresh before retrying"
            }
            self.onChange?()
    }
}
