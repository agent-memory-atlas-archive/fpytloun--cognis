import AppKit
import WebKit

// Fresh UUID-isolated website data store: never opens the installed app's profile.
final class Probe: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
    let storeIdentifier = UUID()
    lazy var store = WKWebsiteDataStore(forIdentifier: storeIdentifier)
    var web: WKWebView!
    var phase = 0
    var navigationStatus = "not-started"
    var evaluationStatus = "not-started"
    var lastMainPhase = "not-observed"
    var lastPeerPhase = "not-observed"
    var unexpectedErrors = 0
    var pollCallbacks = 0
    var pendingBoundaries = Set<String>()
    var expectedNavigation: WKNavigation?
    var initialDocument: String?
    var currentDocument: String?
    var initialInvocationStarted = false
    var reloadInvocationStarted = false
    // Read-only observation bridge; does not suppress browser error events.
    let observationScript = #"""
    (() => {
      let phase = 'document:start';
      const documentID = crypto.randomUUID();
      Object.defineProperty(window, '__attachmentDiagnosticDocument', { value: documentID });
      const names = new Set(['Error','TypeError','ReferenceError','SyntaxError','DataCloneError',
        'AbortError','InvalidStateError','TransactionInactiveError','QuotaExceededError','SecurityError','NotFoundError']);
      const nameOf = value => names.has(value?.name) ? value.name : 'UnknownError';
      const send = (kind, name = '', expected = false) =>
        window.webkit.messageHandlers.attachmentDiagnostic.postMessage({
          kind, name, phase, expected, pathname: location.pathname, documentID,
          frame: window === window.top ? 'main' : 'peer'
        });
      window.addEventListener('attachment-diagnostic-phase', event => {
        if (typeof event.detail !== 'string' || !/^[a-zA-Z0-9:/._-]{1,120}$/.test(event.detail)) return;
        phase = event.detail; send('phase');
      });
      window.addEventListener('error', event => {
        const name = nameOf(event.error);
        send('error', name, phase === 'legacy-clone:callback' && name === 'DataCloneError');
      });
      window.addEventListener('unhandledrejection', event => send('unhandledrejection', nameOf(event.reason)));
      send('document-start');
    })();
    """#
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let item = message.body as? [String: Any],
              let observedPhase = item["phase"] as? String,
              let kind = item["kind"] as? String,
              let frame = item["frame"] as? String,
              let documentID = item["documentID"] as? String,
              UUID(uuidString: documentID) != nil else { return }
        if message.frameInfo.isMainFrame {
            if kind == "document-start" {
                if phase == 0 && initialDocument == nil {
                    initialDocument = documentID
                    currentDocument = documentID
                } else if phase == 1 && currentDocument == nil && documentID != initialDocument {
                    currentDocument = documentID
                }
            }
            guard documentID == currentDocument else {
                diagnose("ignored-old-document"); return
            }
        }
        if frame == "main" { lastMainPhase = observedPhase } else { lastPeerPhase = observedPhase }
        if kind == "phase" {
            if observedPhase.hasSuffix(":start") {
                pendingBoundaries.insert("\(frame):\(observedPhase.dropLast(6))")
            } else if observedPhase.hasSuffix(":settled") {
                pendingBoundaries.remove("\(frame):\(observedPhase.dropLast(8))")
            } else if observedPhase.hasSuffix(":returned") {
                pendingBoundaries.remove("\(frame):\(observedPhase.dropLast(9))")
            } else if let rejection = observedPhase.range(of: ":rejected:") {
                pendingBoundaries.remove("\(frame):\(observedPhase[..<rejection.lowerBound])")
            }
        }
        let expected = item["expected"] as? Bool == true
        if (kind == "error" || kind == "unhandledrejection") && !expected { unexpectedErrors += 1 }
        // These fields come only from the fixed document-start observation script.
        let line: [String: Any] = ["kind": kind, "phase": observedPhase, "frame": frame,
            "name": item["name"] as? String ?? "", "pathname": item["pathname"] as? String ?? "",
            "expectedNegative": expected]
        if let data = try? JSONSerialization.data(withJSONObject: line, options: [.sortedKeys]),
           let text = String(data: data, encoding: .utf8) { print("OBS \(text)") }
        if message.frameInfo.isMainFrame && kind == "phase" && observedPhase == "main:handlers-ready" {
            invokeReadyDocument(documentID)
        }
    }
    func diagnose(_ event: String, error: Error? = nil) {
        let code = error.map { ($0 as NSError).code } ?? 0
        print("NATIVE event=\(event) phase=\(phase) navigation=\(navigationStatus) evaluation=\(evaluationStatus) main=\(lastMainPhase) peer=\(lastPeerPhase) callbacks=\(pollCallbacks) pending=\(pendingBoundaries.sorted()) unexpectedErrors=\(unexpectedErrors) errorCode=\(code)")
    }
    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        guard navigation === expectedNavigation else {
            diagnose("unexpected-navigation"); exit(2)
        }
        navigationStatus = "provisional"; diagnose("navigation-start")
    }
    func webView(_ webView: WKWebView, didCommit navigation: WKNavigation!) {
        navigationStatus = "committed"; diagnose("navigation-commit")
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        navigationStatus = "provisional-failed"; diagnose("navigation-failed", error: error); exit(2)
    }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        navigationStatus = "failed"; diagnose("navigation-failed", error: error); exit(2)
    }
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        navigationStatus = "process-terminated"; diagnose("web-process-terminated"); exit(2)
    }
    func open() {
        guard let url = URL(string: CommandLine.arguments[1]),
              url.scheme == "http", url.host == "127.0.0.1" else {
            print("Loopback fixture URL required"); exit(2)
        }
        print("SYNTHETIC_STORE \(storeIdentifier.uuidString)")
        let config = WKWebViewConfiguration()
        config.websiteDataStore = store
        config.userContentController.add(self, name: "attachmentDiagnostic")
        config.userContentController.addUserScript(WKUserScript(source: observationScript,
            injectionTime: .atDocumentStart, forMainFrameOnly: false))
        web = WKWebView(frame: NSRect(x: 0, y: 0, width: 800, height: 600), configuration: config)
        web.navigationDelegate = self
        expectedNavigation = web.load(URLRequest(url: url))
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard navigation === expectedNavigation else {
            diagnose("unexpected-navigation-finish"); exit(2)
        }
        navigationStatus = "finished"; diagnose("navigation-finish")
    }
    func invokeReadyDocument(_ documentID: String) {
        guard documentID == currentDocument else { return }
        if phase == 0 {
            guard documentID == initialDocument, !initialInvocationStarted else { return }
            // Set before scheduling evaluation; duplicate readiness cannot click twice.
            initialInvocationStarted = true
            evaluationStatus = "initial-click-pending"
            web.evaluateJavaScript("""
              (() => {
                if (window.__attachmentDiagnosticDocument !== '\(documentID)') return 'stale-document';
                const button = document.getElementById('run');
                if (!button || typeof button.onclick !== 'function') return 'missing-run-handler';
                button.click(); return 'invoked';
              })()
              """) { result, error in
                guard self.phase == 0, self.currentDocument == documentID else {
                    self.diagnose("stale-initial-evaluation"); exit(2)
                }
                self.evaluationStatus = error == nil ? "initial-click-returned" : "initial-click-failed"
                self.logHandshake(result)
                self.diagnose("initial-click-callback", error: error)
                guard error == nil, result as? String == "invoked" else {
                    self.diagnose("initial-handshake-failed"); exit(2)
                }
                self.poll()
            }
        } else {
            guard documentID != initialDocument, !reloadInvocationStarted else { return }
            reloadInvocationStarted = true
            evaluationStatus = "reload-call-pending"
            web.evaluateJavaScript("""
              (() => {
                if (window.__attachmentDiagnosticDocument !== '\(documentID)') return 'stale-document';
                if (typeof window.verifyReload !== 'function') return 'missing-reload-handler';
                window.verifyReload(); return 'invoked';
              })()
              """) { result, error in
                    guard self.phase == 1, self.currentDocument == documentID else {
                        self.diagnose("stale-reload-evaluation"); exit(2)
                    }
                    self.evaluationStatus = error == nil ? "reload-call-returned" : "reload-call-failed"
                    self.logHandshake(result)
                    self.diagnose("reload-callback", error: error)
                    guard error == nil, result as? String == "invoked" else {
                        self.diagnose("reload-handshake-failed"); exit(2)
                    }
                    self.poll()
            }
        }
    }
    func logHandshake(_ result: Any?) {
        let allowed = ["invoked", "missing-run-handler", "missing-reload-handler", "stale-document"]
        let value = result as? String
        let safeValue = value.map { allowed.contains($0) ? $0 : "unrecognized" } ?? "not-string"
        let type: String
        if result == nil { type = "nil" }
        else if result is String { type = "String" }
        else if result is NSNull { type = "NSNull" }
        else if result is NSNumber { type = "NSNumber" }
        else if result is NSArray { type = "NSArray" }
        else if result is NSDictionary { type = "NSDictionary" }
        else { type = "other" }
        print("HANDSHAKE phase=\(phase) value=\(safeValue) nativeType=\(type)")
    }
    func poll() {
        evaluationStatus = "result-poll-pending"
        web.evaluateJavaScript("document.getElementById('result').textContent") { result, error in
            self.pollCallbacks += 1
            self.evaluationStatus = error == nil ? "result-poll-returned" : "result-poll-failed"
            if let error { self.diagnose("result-evaluation-failed", error: error); exit(2) }
            let text = result as? String ?? ""
            if text.hasPrefix("{") {
                guard let data = text.data(using: .utf8),
                      let report = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
                    self.diagnose("result-json-invalid"); exit(2)
                }
                var safeReport = report
                safeReport.removeValue(forKey: "partial")
                if let negative = report["negative"] as? [String: Any] {
                    safeReport["negative"] = ["name": negative["name"] as? String ?? "UnknownError"]
                }
                if let safeData = try? JSONSerialization.data(withJSONObject: safeReport, options: [.sortedKeys]),
                   let safeText = String(data: safeData, encoding: .utf8) { print("PHASE \(self.phase): \(safeText)") }
                guard report["failure"] == nil, self.unexpectedErrors == 0 else {
                    self.diagnose("fixture-failed"); exit(2)
                }
                if self.phase == 0 {
                    let keys = ["sameReservation", "sameActivation", "directBlocked", "preparingNotDrained",
                                "consumed", "sameRetry", "receiptStored", "receiptUnchanged",
                                "stagingRetained", "staleRetained", "revoked", "oneSend", "oneUpload", "modeSemantics"]
                    guard let protocolResult = report["protocol"] as? [String: Bool],
                          keys.allSatisfy({ protocolResult[$0] == true }),
                          let bytes = report["bytes"] as? [[String: Any]], bytes.count == 4,
                          bytes.allSatisfy({ $0["committed"] as? Bool == true && $0["equal"] as? Bool == true }),
                          report["metadata"] as? Bool == true,
                          report["revoked"] as? Bool == true,
                          (report["negative"] as? [String: Any])?["name"] as? String == "AbortError"
                    else { self.diagnose("protocol-assertion-failed"); exit(2) }
                } else {
                    let keys = ["reloadBinding", "reloadReceipt", "reloadUploadReceipt",
                                "reloadMetadata", "reloadPNG", "reloadJPEG", "reloadAllFourBytes"]
                    guard keys.allSatisfy({ report[$0] as? Bool == true }) else {
                        self.diagnose("reload-assertion-failed"); exit(2)
                    }
                }
                if self.phase == 0 {
                    self.phase = 1
                    self.currentDocument = nil
                    self.expectedNavigation = self.web.reload()
                } else { exit(0) }
            } else {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { self.poll() }
            }
        }
    }
}
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let probe = Probe()
probe.open()
DispatchQueue.main.asyncAfter(deadline: .now() + 50) { probe.diagnose("TIMEOUT"); exit(3) }
app.run()
