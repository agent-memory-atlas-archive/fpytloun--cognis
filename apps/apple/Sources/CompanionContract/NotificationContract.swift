import Foundation

public struct NotificationTarget: Codable, Equatable, Sendable {
    public let kind: String
    public let target: String
    public init(kind: String, target: String) { self.kind = kind; self.target = target }
    public var isValid: Bool {
        (kind == "notifications" && target.isEmpty)
            || (["chat", "task"].contains(kind) && validIdentifier(target))
    }
}

public struct NativeNotificationIntent: Sendable {
    public let scope: String
    public let id: String
    public let target: NotificationTarget
    public let presentation: NotificationPresentation
}

public struct NotificationApproval: Codable, Equatable, Sendable {
    public let actionId: String
    public let revision: Int
    public let submissionId: String
    public var isValid: Bool {
        validIdentifier(actionId) && revision > 0 && revision <= 9_007_199_254_740_991
            && UUID(uuidString: submissionId) != nil
    }
}

public struct NotificationSender: Codable, Equatable, Sendable {
    public let id: String
    public let name: String
    public let png: String?
    public var image: Data? { png.flatMap { Data(base64Encoded: $0) } }
    private var boundedImage: Bool {
        guard let data = image, data.count >= 24,
              data.starts(with: [137, 80, 78, 71, 13, 10, 26, 10]) else { return false }
        func dimension(_ start: Int) -> UInt32 {
            data[start..<(start + 4)].reduce(UInt32(0)) { ($0 << 8) | UInt32($1) }
        }
        return (1...256).contains(dimension(16)) && (1...256).contains(dimension(20))
    }
    public var isValid: Bool {
        validIdentifier(id) && validNotificationText(name, limit: 80) && !name.isEmpty
            && (png == nil || (png!.utf8.count <= 24000 && boundedImage))
    }
}

public struct NotificationPresentation: Codable, Equatable, Sendable {
    public let title: String
    public let subtitle: String
    public let body: String
    public let sender: NotificationSender?
    public let approval: NotificationApproval?
    public var isValid: Bool {
        !title.isEmpty && validNotificationText(title, limit: 80)
            && validNotificationText(subtitle, limit: 160) && validNotificationText(body, limit: 240)
            && (sender?.isValid ?? true) && (approval?.isValid ?? true)
            && !(sender != nil && approval != nil)
    }
}

public func validNotificationText(_ text: String, limit: Int) -> Bool {
    text.utf16.count <= limit && !text.unicodeScalars.contains {
        CharacterSet.controlCharacters.contains($0) || (0x202a...0x202e).contains($0.value)
            || (0x2066...0x2069).contains($0.value)
    }
}
