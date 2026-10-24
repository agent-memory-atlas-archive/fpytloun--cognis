import AppKit
import CryptoKit
@preconcurrency import UserNotifications
import CompanionContract

struct NotificationReview: Codable, Sendable {
    let profile: String
    let account: String
    let destination: NotificationTarget
    var scope: String? = nil
    var approval: NotificationApproval? = nil
    var isValid: Bool {
        (try? ServerProfile(profile)) != nil && account.utf8.count <= 254
            && account.contains("@") && destination.isValid && (approval?.isValid ?? true)
    }
    var command: [String: Any] {
        ["type": "notification-review", "account": account,
         "kind": destination.kind, "target": destination.target]
    }
}

@MainActor
protocol NativeNotificationDelivering {
    func authorizationStatus() async -> String
    func authorized() async -> Bool
    func requestPermission() async throws -> Bool
    func add(identifier: String, review: NotificationReview, presentation: NotificationPresentation) async throws
    func clear()
    func remove(identifier: String)
}

@MainActor
final class SystemNotificationDelivery: NativeNotificationDelivering {
    let center = UNUserNotificationCenter.current()
    // No supported Apple provisioning is configured. Do not attempt communication
    // intents in ad-hoc builds, even if content.updating could appear to succeed.
    static let communicationPresentation = "unavailable-standard-notifications"
    /// Read-only support evidence: no permission request, categories, or app state changes.
    func diagnostics() async -> [String: Any] {
        let settings = await center.notificationSettings()
        return [
            "bundleIdentifier": Bundle.main.bundleIdentifier ?? "",
            "bundleName": Bundle.main.object(forInfoDictionaryKey: "CFBundleName") as? String ?? "",
            "displayName": Bundle.main.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String ?? "",
            "authorization": await authorizationStatus(),
            "authorizationRaw": settings.authorizationStatus.rawValue,
            "alertRaw": settings.alertSetting.rawValue,
            "soundRaw": settings.soundSetting.rawValue,
            "badgeRaw": settings.badgeSetting.rawValue,
            "notificationCenterRaw": settings.notificationCenterSetting.rawValue,
            "lockScreenRaw": settings.lockScreenSetting.rawValue,
            "errorDomain": NSNull(), "errorCode": NSNull(),
            "permissionRequested": false,
            "communicationPresentation": Self.communicationPresentation,
        ]
    }
    func authorizationStatus() async -> String {
        switch await center.notificationSettings().authorizationStatus {
        case .notDetermined: return "not-determined"
        case .denied: return "denied"
        case .authorized: return "authorized"
        case .provisional: return "provisional"
        case .ephemeral: return "ephemeral"
        @unknown default: return "unavailable"
        }
    }
    func authorized() async -> Bool { await center.notificationSettings().authorizationStatus == .authorized }
    func requestPermission() async throws -> Bool {
        try await center.requestAuthorization(options: [.alert, .sound, .badge])
    }
    static func content(review: NotificationReview, presentation: NotificationPresentation,
                        previews: Bool) throws -> UNMutableNotificationContent {
        let content = UNMutableNotificationContent()
        content.title = presentation.title
        content.subtitle = presentation.subtitle
        content.body = previews ? presentation.body : "Open Cognis to review."
        content.categoryIdentifier = presentation.approval == nil ? "COGNIS_REVIEW" : "TOOL-APPROVAL"
        content.sound = .default
        content.userInfo = ["review": try JSONEncoder().encode(review)]
        return content
    }
    func add(identifier: String, review: NotificationReview, presentation: NotificationPresentation) async throws {
        let content = try Self.content(review: review, presentation: presentation,
            previews: UserDefaults.standard.object(forKey: "notificationPreviews") as? Bool ?? true)
        try await center.add(UNNotificationRequest(identifier: identifier, content: content, trigger: nil))
    }
    func clear() { center.removeAllPendingNotificationRequests(); center.removeAllDeliveredNotifications() }
    func remove(identifier: String) {
        center.removePendingNotificationRequests(withIdentifiers: [identifier])
        center.removeDeliveredNotifications(withIdentifiers: [identifier])
    }
}

/// Owns OS effects and in-flight generation fences. Stores only bounded hashed dedup IDs.
@MainActor
final class NativeNotificationCoordinator: NSObject, UNUserNotificationCenterDelegate {
    private let delivery: any NativeNotificationDelivering
    private let defaults: UserDefaults?
    private var scope = ""
    private var account: String?
    private var profile: String?
    private var serial = 0
    private var seen: [String]
    var onReview: ((NotificationReview) -> Void)?
    var onAction: ((NotificationReview, String) -> Void)?
    var isObserved: (NotificationTarget) -> Bool = { _ in false }
    private(set) var permissionStatus = "Use Enable Notifications to request permission"
    private(set) var authorization = "checking"
    private(set) var permissionError: (domain: String, code: Int)?
    var status: [String: Any] {
        ["type": "notification-status", "authorization": authorization, "message": permissionStatus,
         "errorDomain": permissionError.map { $0.domain as Any } ?? NSNull(),
         "errorCode": permissionError.map { $0.code as Any } ?? NSNull()]
    }
    func refreshPermission() async {
        authorization = await delivery.authorizationStatus()
        if ["authorized", "provisional", "ephemeral"].contains(authorization) { permissionError = nil }
        permissionStatus = Self.permissionMessage(authorization, error: permissionError)
    }
    static func permissionMessage(_ authorization: String, error: (domain: String, code: Int)?) -> String {
        if let error {
            let reason = error.domain == UNErrorDomain && error.code == UNError.Code.notificationsNotAllowed.rawValue
                ? "macOS did not allow notifications" : "Notification authorization failed"
            return "\(reason) (\(error.domain), code \(error.code)). Review Notification Settings and the app's signing identity."
        }
        switch authorization {
        case "authorized", "provisional", "ephemeral": return "Notifications enabled"
        case "denied": return "Notifications denied by macOS. Allow them in Notification Settings."
        case "not-determined": return "Notifications have not been enabled. Use the native Enable Notifications action."
        default: return "macOS notification status is unavailable."
        }
    }

    init(delivery: any NativeNotificationDelivering, defaults: UserDefaults? = nil) {
        self.delivery = delivery; self.defaults = defaults
        seen = Array((defaults?.stringArray(forKey: "notificationDedup") ?? []).suffix(512))
        super.init()
    }
    static func system() -> NativeNotificationCoordinator {
        let delivery = SystemNotificationDelivery()
        let owner = NativeNotificationCoordinator(delivery: delivery, defaults: .standard)
        delivery.center.delegate = owner
        delivery.center.setNotificationCategories(categories)
        return owner
    }
    static var categories: Set<UNNotificationCategory> {
        [UNNotificationCategory(identifier: "COGNIS_REVIEW",
            actions: [UNNotificationAction(identifier: "review", title: "Review", options: [.foreground])],
            intentIdentifiers: [], options: []),
            UNNotificationCategory(identifier: "TOOL-APPROVAL", actions: [
                UNNotificationAction(identifier: "approve", title: "Approve", options: [.authenticationRequired]),
                UNNotificationAction(identifier: "deny", title: "Deny", options: [.authenticationRequired, .destructive]),
            ], intentIdentifiers: [], options: [])]
    }
    func setScope(_ value: String, account: String?, profile: String?) {
        guard value != scope || account != self.account || profile != self.profile else { return }
        serial += 1; scope = value; self.account = account; self.profile = profile
        delivery.clear()
    }
    func invalidate() { setScope(UUID().uuidString, account: nil, profile: nil) }

    /// Called only by the native menu selector, never by startup or the web bridge.
    func enableFromNativeMenu() async {
        do {
            let granted = try await delivery.requestPermission()
            permissionError = nil
            await refreshPermission()
            authorization = granted ? "authorized" : "denied"
            permissionStatus = Self.permissionMessage(authorization, error: nil)
        } catch {
            let failure = error as NSError
            permissionError = (failure.domain, failure.code)
            await refreshPermission()
        }
    }
    func receive(_ intent: NativeNotificationIntent) async {
        guard intent.scope == scope, let account, let profile,
              !isObserved(intent.target) else { return }
        let epoch = serial
        let digest = SHA256.hash(data: Data("\(profile)\u{0}\(account)\u{0}\(intent.id)".utf8))
            .map { String(format: "%02x", $0) }.joined()
        guard !seen.contains(digest), await delivery.authorized(),
              epoch == serial, intent.scope == scope, !seen.contains(digest),
              !isObserved(intent.target) else { return }
        seen.append(digest); seen = Array(seen.suffix(512))
        defaults?.set(seen, forKey: "notificationDedup")
        let identifier = digest + ":" + scope
        do {
            try await delivery.add(identifier: identifier,
                review: NotificationReview(profile: profile, account: account, destination: intent.target,
                    scope: scope, approval: intent.presentation.approval), presentation: intent.presentation)
            // Scope may have changed while UNUserNotificationCenter was adding.
            if epoch != serial { delivery.remove(identifier: identifier) }
        } catch { /* No payload/error logging and no implicit permission prompt. */ }
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse, withCompletionHandler completionHandler: @escaping () -> Void) {
        let allowed = response.actionIdentifier == UNNotificationDefaultActionIdentifier || response.actionIdentifier == "review"
        let data = response.notification.request.content.userInfo["review"] as? Data
        let review = data.flatMap { try? JSONDecoder().decode(NotificationReview.self, from: $0) }
        Task { @MainActor [weak self] in
            guard let self, let review else { return }
            self.respond(review, action: response.actionIdentifier, reviewAllowed: allowed)
        }
        completionHandler()
    }
    func respond(_ review: NotificationReview, action: String, reviewAllowed: Bool = true) {
        guard review.isValid else { return }
        if ["approve", "deny"].contains(action) {
            if review.scope == scope, review.account == account, review.profile == profile,
               review.approval?.isValid == true {
                onAction?(review, action)
            } else { onReview?(review) }
        } else if reviewAllowed { onReview?(review) }
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter,
        willPresent notification: UNNotification) async -> UNNotificationPresentationOptions {
        let data = notification.request.content.userInfo["review"] as? Data
        let review = data.flatMap { try? JSONDecoder().decode(NotificationReview.self, from: $0) }
        return await MainActor.run {
            guard let review, review.isValid, review.account == self.account,
                  review.profile == self.profile, review.scope == self.scope,
                  !self.isObserved(review.destination) else { return [] }
            return [.banner, .sound]
        }
    }
}
