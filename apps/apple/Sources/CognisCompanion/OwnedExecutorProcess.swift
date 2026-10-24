import Foundation
import Darwin
import CompanionContract

/// The spawned CLI is a new process-group leader; never signal our own group.
/// TERM lets Python unwind/reap its current subprocess. KILL fences remaining
/// owned descendants, then waitpid reaps the direct child (orphans are OS-reaped).
struct OwnedExecutorCancellation {
    static func cancel(pid: pid_t,
                       signal: (pid_t, Int32) -> Int32 = Darwin.kill,
                       grace: () -> Void = { usleep(1_000_000) },
                       reap: (pid_t) -> Void = { pid in
                           var status: Int32 = 0
                           while waitpid(pid, &status, 0) == -1 && errno == EINTR {}
                       }) {
        guard pid > 1 else { return }
        _ = signal(-pid, SIGTERM)
        grace()
        _ = signal(-pid, SIGKILL)
        reap(pid)
    }
}

/// Fixed argv, minimal environment, no shell, bounded output and monotonic deadline.
struct BoundedLocalProcess: LocalProcessRunning {
    private func strings<T>(_ values: [String], _ body: ([UnsafeMutablePointer<CChar>?]) -> T) -> T {
        let pointers = values.map { strdup($0) }
        defer { pointers.forEach { free($0) } }
        return body(pointers + [nil])
    }
    func run(binary: URL, arguments: [String]) throws -> LocalProcessResult {
        var descriptors: [Int32] = [0, 0]
        guard pipe(&descriptors) == 0 else { throw HostError.invalidMessage }
        let input = descriptors[0], output = descriptors[1]
        defer { close(input) }
        var writerOpen = true
        defer { if writerOpen { close(output) } }
        var attributes: posix_spawnattr_t?
        var actions: posix_spawn_file_actions_t?
        guard posix_spawnattr_init(&attributes) == 0 else { throw HostError.invalidMessage }
        defer { posix_spawnattr_destroy(&attributes) }
        guard posix_spawn_file_actions_init(&actions) == 0 else { throw HostError.invalidMessage }
        defer { posix_spawn_file_actions_destroy(&actions) }
        // All descendants inherit this owned group. CLOEXEC_DEFAULT prevents
        // leaking unrelated application descriptors into Homebrew/Python.
        guard posix_spawnattr_setflags(&attributes, Int16(POSIX_SPAWN_SETPGROUP | POSIX_SPAWN_CLOEXEC_DEFAULT)) == 0,
              posix_spawnattr_setpgroup(&attributes, 0) == 0,
              posix_spawn_file_actions_addopen(&actions, STDIN_FILENO, "/dev/null", O_RDONLY, 0) == 0,
              posix_spawn_file_actions_addopen(&actions, STDERR_FILENO, "/dev/null", O_WRONLY, 0) == 0,
              posix_spawn_file_actions_adddup2(&actions, output, STDOUT_FILENO) == 0,
              posix_spawn_file_actions_addclose(&actions, input) == 0,
              posix_spawn_file_actions_addclose(&actions, output) == 0 else { throw HostError.invalidMessage }
        var pid: pid_t = 0
        let environment = ["HOME=" + NSHomeDirectory(), "PATH=/usr/bin:/bin:/usr/sbin:/sbin",
                           "LANG=en_US.UTF-8", "HOMEBREW_NO_AUTO_UPDATE=1", "HOMEBREW_NO_INSTALL_FROM_API=1"]
        let error = strings([binary.path] + arguments) { argv in
            strings(environment) { env in
                posix_spawn(&pid, binary.path, &actions, &attributes, argv, env)
            }
        }
        close(output)
        writerOpen = false
        guard error == 0 else { throw HostError.invalidMessage }
        _ = fcntl(input, F_SETFL, O_NONBLOCK)
        let clock = ContinuousClock(), deadline = ContinuousClock.now + .seconds(40)
        var data = Data(), buffer = [UInt8](repeating: 0, count: 4096)
        var status: Int32 = 0, reaped = false
        while true {
            let count = read(input, &buffer, buffer.count)
            if count > 0 { data.append(contentsOf: buffer.prefix(count)) }
            if data.count > 16384 || clock.now > deadline {
                OwnedExecutorCancellation.cancel(pid: pid)
                throw HostError.invalidMessage
            }
            if !reaped { reaped = waitpid(pid, &status, WNOHANG) == pid }
            if count == 0 && reaped { break }
            usleep(10_000)
        }
        return LocalProcessResult(code: status & 0x7f == 0 ? (status >> 8) & 0xff : -1, data: data)
    }
}
