public enum LoginRegistrationStatus: Equatable, Sendable {
    case enabled, notRegistered, requiresApproval, notFound
}

public struct LaunchPolicy: Equatable, Sendable {
    public let background: Bool
    public init(loginItem: Bool, startInBackground: Bool) {
        background = loginItem || startInBackground
    }
    public var initialPath: String { background ? "/companion" : "/" }
    public var showMain: Bool { !background }
    public static let terminateOnLastWindowClose = false
}
