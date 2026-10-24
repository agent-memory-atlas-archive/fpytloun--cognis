import XCTest
import Darwin
import CompanionContract
@testable import CognisCompanion

private struct FixtureRunner: LocalProcessRunning {
    let code: Int32
    let data: Data
    func run(binary: URL, arguments: [String]) throws -> LocalProcessResult {
        XCTAssertEqual(binary.path, "/opt/homebrew/bin/brew")
        XCTAssertEqual(arguments, ["services", "info", "--json", "fpytloun/tap/cognis-executor"])
        return LocalProcessResult(code: code, data: data)
    }
}

private final class RecordingServiceRunner: LocalProcessRunning, @unchecked Sendable {
    private let lock = NSLock()
    private var calls: [[String]] = []
    let status: Data
    init() {
        status = Data("""
        [{"name":"cognis-executor","service_name":"sh.brew.cognis-executor",
          "running":true,"loaded":true,"status":"started","user":"\(NSUserName())",
          "command":"/opt/homebrew/opt/cognis-executor/bin/cognis-executor"}]
        """.utf8)
    }
    func run(binary: URL, arguments: [String]) throws -> LocalProcessResult {
        lock.lock(); defer { lock.unlock() }
        XCTAssertEqual(binary.path, "/opt/homebrew/bin/brew")
        calls.append(arguments)
        return LocalProcessResult(code: 0, data: arguments == ExecutorAction.status.arguments
            ? status : Data("Homebrew operation completed".utf8))
    }
    func snapshot() -> [[String]] { lock.lock(); defer { lock.unlock() }; return calls }
}

@MainActor
final class ExecutorAdapterTests: XCTestCase {
    func testExplicitServiceActionsAlwaysRefreshStructuredStatus() async {
        for action in [ExecutorAction.start, .stop, .restart] {
            let runner = RecordingServiceRunner()
            let adapter = LocalExecutorAdapter(runner: runner,
                discover: { URL(fileURLWithPath: "/opt/homebrew/bin/brew") })
            await adapter.perform(.status)
            await adapter.perform(action)
            XCTAssertEqual(runner.snapshot(), [
                ExecutorAction.status.arguments, action.arguments, ExecutorAction.status.arguments
            ])
            XCTAssertEqual(adapter.menu().items.first?.title, "running")
        }
    }
    func testInjectedStatusAndUnsupportedVersion() async {
        let data = Data("""
        [{"name":"cognis-executor","service_name":"sh.brew.cognis-executor",
          "running":true,"loaded":true,"status":"started","user":"\(NSUserName())",
          "command":"/opt/homebrew/opt/cognis-executor/bin/cognis-executor"}]
        """.utf8)
        let adapter = LocalExecutorAdapter(runner: FixtureRunner(code: 0, data: data),
                                          discover: { URL(fileURLWithPath: "/opt/homebrew/bin/brew") })
        await adapter.perform(.status)
        XCTAssertEqual(adapter.menu().items.first?.title, "running")
        let old = LocalExecutorAdapter(runner: FixtureRunner(code: 2, data: Data("old CLI".utf8)),
                                      discover: { URL(fileURLWithPath: "/opt/homebrew/bin/brew") })
        await old.perform(.status)
        XCTAssertTrue(old.menu().items.first?.title.contains("could not be verified") == true)
        XCTAssertEqual(old.menu().items.filter { $0.isEnabled }.count, 1)
    }
    func testFixedArgumentsAndBoundedContract() throws {
        XCTAssertEqual(ExecutorAction.restart.arguments, ["services", "restart", "fpytloun/tap/cognis-executor"])
        XCTAssertThrowsError(try ExecutorObservation.decode(Data(repeating: 0, count: 16385)))
        XCTAssertThrowsError(try ExecutorObservation.decode(Data(#"{"schema":2}"#.utf8)))
    }
    func testHomebrewStatusRejectsAmbiguityAndWrongOwnership() throws {
        let status = """
        [{"name":"cognis-executor","service_name":"sh.brew.cognis-executor",
          "running":false,"loaded":false,"status":"none"}]
        """
        let value = try ExecutorObservation.homebrew(Data(status.utf8), prefix: "/opt/homebrew", user: "mac-owner")
        XCTAssertEqual(value.state, "stopped")
        XCTAssertTrue(value.owned)
        XCTAssertThrowsError(try ExecutorObservation.homebrew(Data("[]".utf8), prefix: "/opt/homebrew", user: "mac-owner"))
        XCTAssertThrowsError(try ExecutorObservation.homebrew(Data(status.utf8), prefix: "/tmp", user: "mac-owner"))
        let wrongUser = status.replacingOccurrences(of: "\"status\":\"none\"", with: "\"status\":\"none\",\"user\":\"another-user\"")
        XCTAssertThrowsError(try ExecutorObservation.homebrew(Data(wrongUser.utf8), prefix: "/opt/homebrew", user: "mac-owner"))
        let wrongCommand = status.replacingOccurrences(of: "\"status\":\"none\"", with: "\"status\":\"none\",\"command\":\"/tmp/cognis-executor\"")
        XCTAssertThrowsError(try ExecutorObservation.homebrew(Data(wrongCommand.utf8), prefix: "/opt/homebrew", user: "mac-owner"))
        XCTAssertThrowsError(try ExecutorObservation.homebrew(Data("started".utf8), prefix: "/opt/homebrew", user: "mac-owner"))
    }
    func testTimeoutTerminatesOwnedMutationTreeBeforeReapingParent() {
        var effects: [String] = []
        var mutationRunning = true
        OwnedExecutorCancellation.cancel(pid: 42042, signal: { group, signal in
            XCTAssertEqual(group, -42042, "Must signal the owned group, not only Python")
            effects.append(signal == SIGTERM ? "term-tree" : "kill-tree")
            if signal == SIGKILL { mutationRunning = false }
            return 0
        }, grace: { effects.append("unwind-python") }, reap: { pid in
            XCTAssertEqual(pid, 42042)
            XCTAssertFalse(mutationRunning)
            effects.append("reap-parent")
        })
        XCTAssertEqual(effects, ["term-tree", "unwind-python", "kill-tree", "reap-parent"])
    }
}
