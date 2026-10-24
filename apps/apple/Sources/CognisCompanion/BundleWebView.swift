import AppKit
import WebKit
import UniformTypeIdentifiers
import CompanionContract

/// The nonactivating rail accepts its first click and tracks hover while inactive.
@MainActor
final class RailWebView: WKWebView {
    var onPointerChange: (() -> Void)?
    private var railTracking: NSTrackingArea?
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let railTracking { removeTrackingArea(railTracking) }
        let area = NSTrackingArea(rect: .zero,
            options: [.mouseEnteredAndExited, .mouseMoved, .activeAlways, .inVisibleRect],
            owner: self, userInfo: nil)
        addTrackingArea(area); railTracking = area
    }
    override func mouseEntered(with event: NSEvent) { super.mouseEntered(with: event); onPointerChange?() }
    override func mouseExited(with event: NSEvent) { super.mouseExited(with: event); onPointerChange?() }
    override func mouseMoved(with event: NSEvent) { super.mouseMoved(with: event); onPointerChange?() }
}

@MainActor
final class BundleAssets: NSObject, WKURLSchemeHandler {
    let root: URL
    let origin: String
    private(set) var served: [String: String] = [:]
    private(set) var failed: Set<String> = []
    init(root: URL, origin: String) { self.root = root; self.origin = origin }

    func webView(_ webView: WKWebView, start task: WKURLSchemeTask) {
        guard task.request.httpMethod == "GET", let url = task.request.url,
              let file = bundledAsset(url, root: root), let bytes = try? Data(contentsOf: file)
        else {
            failed.insert(task.request.url?.lastPathComponent ?? "unresolved")
            task.didFailWithError(URLError(.fileDoesNotExist))
            return
        }
        let type = file.pathExtension == "js" ? "text/javascript"
            : UTType(filenameExtension: file.pathExtension)?.preferredMIMEType ?? "application/octet-stream"
        served[url.path] = type
        task.didReceive(HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: [
            // Nested ES modules have the scheme's opaque origin. These are public,
            // immutable bundle assets only, never authenticated server responses.
            "Content-Type": type, "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"
        ])!)
        task.didReceive(bytes)
        task.didFinish()
    }
    func webView(_ webView: WKWebView, stop task: WKURLSchemeTask) {}
}

@MainActor
final class BundleWebView: NSObject, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler {
    let web: WKWebView
    let profile: ServerProfile
    let generation = UUID().uuidString
    let assets: BundleAssets
    private var trusted = false
    private var initialURL: URL?
    private var html: String
    var onMessage: ((BridgeMessage) -> Void)?
    var onReady: (() -> Void)?
    var onFailure: ((String) -> Void)?
    var onReload: (() -> Void)?
    var onOwnedInteraction: ((Bool) -> Void)?
    enum NativeAction { case externalOpen, fileChooser, download, childNavigationRejected, childFileChooserRejected }
    var onNativeAction: ((NativeAction) -> Void)?
    private let externalOpener: (URL) -> Void

    init(profile: ServerProfile, root: URL, surface: String = "main",
         externalOpener: @escaping (URL) -> Void = { NSWorkspace.shared.open($0) }) throws {
        self.externalOpener = externalOpener
        self.profile = profile
        assets = BundleAssets(root: root, origin: profile.origin.absoluteString)
        let exportedHTML = try String(contentsOf: root.appendingPathComponent("index.html"), encoding: .utf8)
        // HTTPS documents cannot fetch custom-scheme executable modules in
        // WebKit. Packaging embeds the complete canonical executable graph.
        // Refuse a raw export instead of weakening CSP or changing origins.
        guard exportedHTML.range(of: #"__sveltekit_[a-z0-9]+\.app\.start\("#, options: .regularExpression) != nil,
              !exportedHTML.contains("\"/_app/env.js\"") else {
            throw HostError.incompatibleProtocol
        }
        html = exportedHTML
            .replacingOccurrences(of: "<link rel=\"manifest\" href=\"/manifest.webmanifest\" />", with: "")
        let config = WKWebViewConfiguration()
        config.websiteDataStore = WKWebsiteDataStore(forIdentifier: profile.storageIdentifier)
        config.setURLSchemeHandler(assets, forURLScheme: "cognisbundle")
        web = surface == "rail" ? RailWebView(frame: .zero, configuration: config)
                               : WKWebView(frame: .zero, configuration: config)
        if surface == "rail" {
            web.setValue(false, forKey: "drawsBackground")
            web.underPageBackgroundColor = .clear
        }
        super.init()
        web.navigationDelegate = self
        web.uiDelegate = self
        config.userContentController.add(self, name: "cognis")
        let data = try JSONSerialization.data(withJSONObject: [
            "version": 1, "generation": generation, "server": profile.origin.absoluteString,
            "surface": surface
        ])
        let json = String(decoding: data, as: UTF8.self)
        config.userContentController.addUserScript(WKUserScript(
            source: "Object.defineProperty(window, '__cognisNative', {value:Object.freeze(\(json)),writable:false,configurable:false}); { const mark = () => document.documentElement.setAttribute('data-native-surface','\(surface)'); if (document.documentElement) mark(); else document.addEventListener('DOMContentLoaded',mark,{once:true}); }",
            injectionTime: .atDocumentStart, forMainFrameOnly: true
        ))
        config.userContentController.addUserScript(WKUserScript(source: """
            window.__cognisNativeStartupErrors = [];
            const record = value => {
              if (window.__cognisNativeStartupErrors.length < 10) window.__cognisNativeStartupErrors.push(value);
            };
            const filename = value => {
              try {
                const path = new URL(value, location.href).pathname;
                return path.startsWith('/_app/') && path.endsWith('.js')
                  ? path.split('/').pop().slice(0,128) : 'non-bundle-script';
              }
              catch { return 'unresolved'; }
            };
            document.addEventListener('securitypolicyviolation', event => {
              if (event.violatedDirective.startsWith('script-src'))
                record({file:filename(event.blockedURI),directive:event.violatedDirective});
            });
            window.addEventListener('error', event => {
              if (event.target instanceof HTMLScriptElement ||
                  (event.target instanceof HTMLLinkElement && event.target.rel === 'modulepreload'))
                record({file:filename(event.target.src || event.target.href),directive:'resource'});
            }, true);
            """, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        web.allowsBackForwardNavigationGestures = false
    }

    func start(path: String) {
        guard validRoute(path), let url = URL(string: path, relativeTo: profile.origin)?.absoluteURL,
              profile.contains(url) else { return }
        initialURL = url
        trusted = true
        let ws = profile.origin.absoluteString.replacingOccurrences(of: "https://", with: "wss://")
            .replacingOccurrences(of: "http://", with: "ws://")
        // Remote responses must never become executable application frames or scripts.
        let policy = "default-src 'none'; script-src cognisbundle: 'unsafe-inline'; style-src cognisbundle: 'unsafe-inline'; "
            + "connect-src \(profile.origin.absoluteString) \(ws) cognisbundle:; "
            + "img-src https: http: data: blob: cognisbundle:; font-src cognisbundle: data:; "
            + "media-src \(profile.origin.absoluteString) blob: data:; worker-src cognisbundle: blob:; "
            + "frame-src blob:; object-src 'none'; base-uri 'none'; form-action 'none'"
        // The inline graph can contain literal HTML inside executable strings.
        // Add policy to the actual head once, never rewrite those strings.
        guard let head = html.range(of: "<head>") else { return }
        var content = html
        content.insert(contentsOf: "<meta http-equiv=\"Content-Security-Policy\" content=\"\(policy)\">",
                       at: head.upperBound)
        web.loadSimulatedRequest(URLRequest(url: url), responseHTML: content)
    }

    func send(_ payload: [String: Any]) {
        guard trusted else { return }
        var message = payload
        message["version"] = 1
        message["generation"] = generation
        // Fixed expression with structured arguments, not an arbitrary JS capability.
        web.callAsyncJavaScript("window.__cognisNativeReceive?.(command)", arguments: ["command": message],
                                in: nil, in: .page) { _ in }
    }

    func invalidate() {
        trusted = false
        onMessage = nil; onReady = nil; onFailure = nil; onReload = nil; onOwnedInteraction = nil
        web.stopLoading()
        web.configuration.userContentController.removeScriptMessageHandler(forName: "cognis")
        web.configuration.userContentController.removeAllUserScripts()
        web.navigationDelegate = nil
        web.uiDelegate = nil
        // Tear down the old document, including sockets/timers, on profile replacement.
        web.loadHTMLString("<!doctype html><title>Closed</title>", baseURL: nil)
        web.removeFromSuperview()
    }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        let validFrame = trusted && message.webView === web && message.frameInfo.isMainFrame
            && message.frameInfo.request.url.map(profile.contains) == true
            && web.url.map(profile.contains) == true
        do {
            onMessage?(try BridgeMessage.decode(message.body, generation: generation, trustedMainFrame: validFrame))
        } catch HostError.incompatibleProtocol {
            onFailure?("The bundled web/native host protocol is incompatible. Rebuild this app from one source revision.")
        } catch { /* Invalid messages have no side effects and no payload logging. */ }
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping @MainActor @Sendable (WKNavigationActionPolicy) -> Void) {
        if action.targetFrame?.isMainFrame == true, action.request.url == initialURL,
           action.navigationType == .other {
            initialURL = nil
            decisionHandler(.allow)
            return
        }
        let mainSource = isTrustedMainFrame(action.sourceFrame, in: webView)
        if mainSource, action.targetFrame?.isMainFrame == false,
           action.navigationType == .other, !action.shouldPerformDownload,
           let url = action.request.url, isHTMLPreviewBlob(url, profile: profile) {
            decisionHandler(.allow)
            return
        }
        decisionHandler(.cancel)
        guard mainSource, !action.shouldPerformDownload else {
            if !action.sourceFrame.isMainFrame { onNativeAction?(.childNavigationRejected) }
            return
        }
        if action.navigationType == .reload, action.targetFrame?.isMainFrame == true {
            onReload?()
        } else if action.navigationType == .linkActivated { openExternal(action.request.url) }
    }

    private func isTrustedMainFrame(_ frame: WKFrameInfo, in candidate: WKWebView) -> Bool {
        trusted && candidate === web && frame.isMainFrame
            && frame.request.url.map(profile.contains) == true
            && web.url.map(profile.contains) == true
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
                 decisionHandler: @escaping @MainActor @Sendable (WKNavigationResponsePolicy) -> Void) {
        let allowed = trusted && webView === web && response.canShowMIMEType
            && (response.isForMainFrame || response.response.url.map {
                isHTMLPreviewBlob($0, profile: profile)
            } == true)
        decisionHandler(allowed ? .allow : .cancel)
    }

    private func openExternal(_ url: URL?) {
        guard let url, url.user == nil, url.password == nil,
              url.scheme == "https" || url.scheme == "mailto"
                || (url.scheme == "http" && ["127.0.0.1", "localhost", "::1", "[::1]"].contains(url.host ?? ""))
        else { return }
        onNativeAction?(.externalOpen)
        externalOpener(url)
    }
    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
        onNativeAction?(.download)
        download.cancel { _ in }
    }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
        onNativeAction?(.download)
        download.cancel { _ in }
    }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if isTrustedMainFrame(action.sourceFrame, in: webView),
           action.navigationType == .linkActivated, !action.shouldPerformDownload {
            openExternal(action.request.url)
        }
        return nil
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        onReady?()
        Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(3))
            guard let self, self.trusted else { return }
            if let diagnostics = try? await self.web.evaluateJavaScript("""
                document.querySelector('#cognis-startup-recovery')
                  ? JSON.stringify(window.__cognisNativeStartupErrors || []) : null
                """) as? String {
                // Only bounded executable asset filenames/directives, never tokens,
                // origins, URL queries, console payloads or conversation contents.
                NSLog("Cognis bundled startup failure: %@", diagnostics)
                self.onFailure?("Bundled application startup failed. Native diagnostics recorded the blocked or missing script filenames. Reopen Cognis after replacing this app bundle; saved sign-in and drafts remain intact.")
            }
        }
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        if (error as NSError).code != NSURLErrorCancelled { onFailure?("The bundled application could not start.") }
    }
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        onFailure?("The web process stopped. Reopen Cognis to restore the bundled app and saved drafts.")
    }
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping @MainActor @Sendable ([URL]?) -> Void) {
        guard isTrustedMainFrame(frame, in: webView),
              web.window?.isKeyWindow == true else {
            if !frame.isMainFrame { onNativeAction?(.childFileChooserRejected) }
            completionHandler(nil); return
        }
        onNativeAction?(.fileChooser)
        let panel = NSOpenPanel()
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        onOwnedInteraction?(true)
        panel.beginSheetModal(for: web.window!) { [weak self] result in
            self?.onOwnedInteraction?(false)
            completionHandler(result == .OK ? panel.urls : nil)
        }
    }
}
