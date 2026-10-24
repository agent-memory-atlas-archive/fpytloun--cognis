import Foundation
import CompanionContract

/// Discovery is informational compatibility, never updater or service authority.
final class CompatibilityChecker: NSObject, URLSessionTaskDelegate, Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                    completionHandler: @escaping @Sendable (URLRequest?) -> Void) { completionHandler(nil) }

    func check(_ profile: ServerProfile) async -> Bool? {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 10
        configuration.httpShouldSetCookies = false
        let session = URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
        defer { session.invalidateAndCancel() }
        do {
            let url = profile.origin.appendingPathComponent(".well-known/cognis-client.json")
            let (bytes, response) = try await session.data(from: url)
            guard let response = response as? HTTPURLResponse else { return nil }
            guard response.statusCode == 200, bytes.count <= 32768 else { return false }
            return compatibleServer((try? JSONSerialization.jsonObject(with: bytes)) ?? [:])
        } catch { return nil }
    }
}
