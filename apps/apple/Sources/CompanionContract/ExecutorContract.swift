import Foundation

public enum ExecutorAction: String, CaseIterable, Sendable {
    case status, start, stop, restart, logs
    public var arguments: [String] {
        switch self {
        case .status, .logs: ["services", "info", "--json", "fpytloun/tap/cognis-executor"]
        case .start, .stop, .restart: ["services", rawValue, "fpytloun/tap/cognis-executor"]
        }
    }
}

public struct ExecutorObservation: Decodable, Equatable, Sendable {
    public let schema: Int
    public let state: String
    public let owned: Bool
    public let controller: String
    public let ok: Bool
    public let code: String
    public let preview: [String]?

    public static func decode(_ data: Data) throws -> Self {
        guard data.count <= 16384 else { throw HostError.invalidMessage }
        let value = try JSONDecoder().decode(Self.self, from: data)
        guard value.schema == 1, ["unknown", "not_installed", "stopped", "running"].contains(value.state),
              value.controller == "unknown", value.code.count <= 64,
              (value.preview ?? []).count <= 2,
              (value.preview ?? []).allSatisfy({ $0.count <= 256 }) else { throw HostError.invalidMessage }
        return value
    }

    /// Homebrew's structured service contract, including the installed 0.17.1 CLI.
    /// Unknown or ambiguous services fail closed; no status is inferred from prose.
    public static func homebrew(_ data: Data, prefix: String, user: String) throws -> Self {
        struct Service: Decodable {
            let name: String
            let service_name: String
            let running: Bool
            let loaded: Bool
            let status: String
            let user: String?
            let command: String?
            let file: String?
        }
        guard data.count <= 16384, ["/opt/homebrew", "/usr/local"].contains(prefix) else {
            throw HostError.invalidMessage
        }
        let rows = try JSONDecoder().decode([Service].self, from: data)
        guard rows.count == 1, let row = rows.first,
              row.name == "cognis-executor", row.service_name == "sh.brew.cognis-executor",
              ["started", "stopped", "none", "error", "unknown"].contains(row.status),
              row.user == nil || row.user == user,
              row.command == nil || row.command == prefix + "/opt/cognis-executor/bin/cognis-executor"
        else { throw HostError.invalidMessage }
        let healthy = row.running && row.loaded && row.status == "started"
        let stopped = !row.running && !row.loaded && ["stopped", "none"].contains(row.status)
        return Self(schema: 1, state: healthy ? "running" : stopped ? "stopped" : "unknown",
                    owned: healthy || stopped, controller: "unknown", ok: healthy || stopped,
                    code: healthy || stopped ? "observed" : "service_error",
                    preview: ["Homebrew service: \(row.status)", "Controller connection: not verified"])
    }
}
