import Foundation

public enum PackageFlavor: String, Sendable {
    case standard, preview, acceptance
    public var bundleIdentifier: String {
        switch self {
        case .standard: "cz.fpy.cognis.companion"
        case .preview: "cz.fpy.cognis.companion.preview"
        case .acceptance: "cz.fpy.cognis.companion.acceptance"
        }
    }
    public var displayName: String {
        switch self {
        case .standard: "Cognis"
        case .preview: "Cognis Preview"
        case .acceptance: "Cognis Acceptance"
        }
    }
}

public struct PackageConfiguration: Sendable {
    public let flavor: PackageFlavor
    public let fixedProfile: ServerProfile?
    public var allowsServerSelection: Bool { flavor != .acceptance }
    public var displayName: String { flavor.displayName }

    public init(info: [String: Any]) throws {
        guard let name = info["CognisPackageFlavor"] as? String,
              let flavor = PackageFlavor(rawValue: name),
              info["CFBundleIdentifier"] as? String == flavor.bundleIdentifier else {
            throw HostError.invalidMessage
        }
        self.flavor = flavor
        if flavor == .acceptance {
            guard let origin = info["CognisAcceptanceOrigin"] as? String,
                  let profile = try? ServerProfile(origin, storageNamespace: flavor.bundleIdentifier),
                  profile.isAcceptanceServer else { throw HostError.invalidServer }
            fixedProfile = profile
        } else {
            guard info["CognisAcceptanceOrigin"] == nil else { throw HostError.invalidMessage }
            fixedProfile = nil
        }
    }

    public func profile(_ input: String) throws -> ServerProfile {
        let profile = try ServerProfile(input, storageNamespace: flavor.bundleIdentifier)
        guard fixedProfile == nil || profile == fixedProfile else { throw HostError.invalidServer }
        return profile
    }
}
