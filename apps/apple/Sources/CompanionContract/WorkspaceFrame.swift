import Foundation

/// Transport authority only: native never reduces, retains or persists pin state.
public struct WorkspaceFrame: Sendable {
    public let kind: String
    public let document: String
    public let profile: String
    public let account: String
    public let authEpoch: String
    public let ownerEpoch: String?
    public let target: String
    public let revision: Int
    public let id: Int
    public let json: String
    public var value: [String: Any] { (try? JSONSerialization.jsonObject(with: Data(json.utf8))) as? [String: Any] ?? [:] }
    public var scope: String { profile + "\n" + account + "\n" + authEpoch }

    public static func decode(_ body: [String: Any]) throws -> Self {
        let common: Set<String> = ["kind", "document", "profile", "account", "authEpoch", "ownerEpoch", "target", "revision", "id"]
        guard let kind = body["kind"] as? String,
              ["hello", "command", "query", "projection", "result"].contains(kind),
              let document = body["document"] as? String, UUID(uuidString: document) != nil,
              let profile = body["profile"] as? String,
              try ServerProfile(profile).origin.absoluteString == profile,
              let account = body["account"] as? String, !account.isEmpty, account.count <= 254,
              !account.contains(where: \.isWhitespace),
              let authEpoch = body["authEpoch"] as? String, UUID(uuidString: authEpoch) != nil,
              let target = body["target"] as? String,
              target.isEmpty || target == "*" || UUID(uuidString: target) != nil,
              let revision = body["revision"] as? Int, revision >= 0,
              let id = body["id"] as? Int, id >= 0
        else { throw HostError.invalidMessage }
        let epoch = body["ownerEpoch"] as? String
        guard (epoch != nil && UUID(uuidString: epoch!) != nil) || (kind == "hello" && body["ownerEpoch"] is NSNull)
        else { throw HostError.invalidMessage }
        var keys = common
        switch kind {
        case "command":
            keys.insert("intent")
            guard id > 0, target.isEmpty, let intent = body["intent"] as? [String: Any] else { throw HostError.invalidMessage }
            try validateIntent(intent)
        case "query":
            guard id > 0, target.isEmpty else { throw HostError.invalidMessage }
        case "hello":
            guard id == 0, target.isEmpty else { throw HostError.invalidMessage }
        case "result":
            keys.formUnion(["result", "projection"])
            guard id > 0, UUID(uuidString: target) != nil,
                  let result = body["result"] as? [String: Any], result["ok"] is Bool,
                  Set(result.keys).isSubset(of: ["ok", "key", "reason"])
            else { throw HostError.invalidMessage }
            fallthrough
        default:
            keys.insert("projection")
            guard revision > 0, !target.isEmpty,
                  let projection = body["projection"] as? [String: Any],
                  Set(projection.keys) == ["workspace", "agents", "conversations", "background"],
                  let state = projection["workspace"] as? [String: Any],
                  state["owner"] as? String == account,
                  let entries = state["entries"] as? [Any], entries.count <= 10,
                  let agents = state["agents"] as? [Any], agents.count <= 10,
                  projection["agents"] is [Any], projection["conversations"] is [String: Any],
                  projection["background"] is [Any]
            else { throw HostError.invalidMessage }
        }
        guard Set(body.keys) == keys else { throw HostError.invalidMessage }
        let data = try JSONSerialization.data(withJSONObject: body)
        guard data.count <= 524_288, let json = String(data: data, encoding: .utf8) else { throw HostError.invalidMessage }
        return Self(kind: kind, document: document, profile: profile, account: account,
                    authEpoch: authEpoch, ownerEpoch: epoch, target: target, revision: revision, id: id, json: json)
    }
    private static func validateIntent(_ value: [String: Any]) throws {
        func identifier(_ key: String) -> Bool { (value[key] as? String).map(validIdentifier) == true }
        func key(_ name: String) -> Bool {
            guard let text = value[name] as? String, !text.isEmpty, text.count <= 320 else { return false }
            return text.range(of: #"^[A-Za-z0-9_:-]+$"#, options: .regularExpression) != nil
        }
        guard let type = value["type"] as? String else { throw HostError.invalidMessage }
        let keys = Set(value.keys)
        let valid: Bool
        switch type {
        case "pin":
            valid = keys.isSubset(of: ["type", "conversationId", "select", "replaceKey"])
                && identifier("conversationId") && value["select"] is Bool
                && (value["replaceKey"] == nil || key("replaceKey"))
        case "home":
            valid = keys == ["type", "agentId", "conversationId", "pin"]
                && identifier("agentId") && identifier("conversationId") && value["pin"] is Bool
        case "agent":
            valid = keys == ["type", "agentId", "pinned"] && identifier("agentId") && value["pinned"] is Bool
        case "unpin": valid = keys == ["type", "key"] && key("key")
        case "select": valid = keys == ["type", "agentId", "key"] && identifier("agentId") && key("key")
        case "tucked": valid = keys == ["type", "value"] && value["value"] is Bool
        case "position":
            valid = keys == ["type", "value"] && (value["value"] as? Double).map { $0.isFinite && (0...1).contains($0) } == true
        default: valid = false
        }
        guard valid else { throw HostError.invalidMessage }
    }
}

@MainActor
public final class WorkspaceRelay {
    private let profile: String
    private let main: String
    private var authority: String?
    private var retired = Set<String>()
    private var revision = 0
    public init(profile: String, main: String) { self.profile = profile; self.main = main }
    public func route(_ frame: WorkspaceFrame, source: String, documents: Set<String>,
                      reset: () -> Void) -> Set<String> {
        guard frame.profile == profile, frame.document == source, documents.contains(source) else { return [] }
        if source == main {
            guard ["projection", "result"].contains(frame.kind), let epoch = frame.ownerEpoch else { return [] }
            let next = frame.scope + "\n" + epoch
            guard !retired.contains(next) else { return [] }
            if next != authority {
                if let authority { retired.insert(authority) }
                authority = next; revision = 0; reset()
            }
            guard frame.revision > revision else { return [] }
            revision = frame.revision
            return frame.target == "*" ? documents.subtracting([main]) : documents.intersection([frame.target]).subtracting([main])
        }
        guard ["hello", "command", "query"].contains(frame.kind), documents.contains(main) else { return [] }
        if frame.kind != "hello" {
            guard let epoch = frame.ownerEpoch, frame.scope + "\n" + epoch == authority else { return [] }
        }
        return [main]
    }
}
