import Foundation

/// Compare serialized creator origins, not normalized untrusted URLs.
public func isHTMLPreviewBlob(_ url: URL, profile: ServerProfile) -> Bool {
    let prefix = "blob:" + profile.origin.absoluteString + "/"
    let value = url.absoluteString
    guard value.hasPrefix(prefix) else { return false }
    let identifier = String(value.dropFirst(prefix.count))
    guard let uuid = UUID(uuidString: identifier) else { return false }
    return identifier.lowercased() == uuid.uuidString.lowercased()
}
