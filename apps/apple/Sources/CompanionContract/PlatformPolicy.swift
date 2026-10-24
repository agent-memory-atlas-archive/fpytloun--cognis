import Foundation

public enum UpdateAvailability: Equatable {
    case available, managed, unavailable

    public init(info: [String: Any]) {
        if info["CognisDistribution"] as? String == "homebrew" { self = .managed; return }
        guard let feed = info["SUFeedURL"] as? String, let url = URL(string: feed),
              url.scheme == "https", url.host != nil, url.user == nil, url.password == nil,
              url.fragment == nil, let key = info["SUPublicEDKey"] as? String,
              Data(base64Encoded: key)?.count == 32,
              info["SURequireSignedFeed"] as? Bool == true,
              info["SUVerifyUpdateBeforeExtraction"] as? Bool == true,
              info["SUSignedFeedFailureExpirationInterval"] as? Int == 0 else {
            self = .unavailable; return
        }
        self = .available
    }
}

public func compatibleServer(_ value: Any) -> Bool {
    guard let object = value as? [String: Any],
          object["schema_version"] as? Int == 1,
          let product = object["product"] as? [String: Any], product["id"] as? String == "cognis",
          let proto = object["protocol"] as? [String: Any],
          proto["id"] as? String == "cognis-client", proto["version"] as? Int == 1,
          let caps = object["capabilities"] as? [String: Any],
          caps["authentication"] as? Int == 1, caps["chat"] as? Int == 2,
          caps["realtime"] as? Int == 1 else { return false }
    return true
}
