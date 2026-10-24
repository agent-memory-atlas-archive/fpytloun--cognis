import AppKit
import WebKit
import XCTest
import CompanionContract
@testable import CognisCompanion

@MainActor
final class FindInputTests: XCTestCase {
    private let fixture = """
        const now='2026-10-20T00:00:00Z';
        const agent={agent_id:'agent-find',name:'find',display_name:'Find Agent',agent_type:'primary',status:'active',enabled:true,model:'fixture',tools:[],skills:[],profiles:[]};
        const conversation={conversation_id:'conv-find',user_email:'find@acceptance.invalid',agent_id:'agent-find',
          agent_profile_id:null,project_id:null,title:'Find native conversation',title_source:'manual',
          context:{type:'web',ref:null,platform_data:{},memory_labels:{}},active_session_id:'sess-find',
          active_executor_id:null,active_session_status:'active',active_session_completion_reason:null,
          pending_notification_types:[],starred_at:null,status:'active',last_message_at:now,last_read_at:now,
          has_unread:false,has_active_turn:false,managed_agent:null,created_at:now,updated_at:now,conversation_state:null};
        const session={session_id:'sess-find',conversation_id:'conv-find',user_email:'find@acceptance.invalid',
          agent_id:'agent-find',agent_profile_id:null,status:'active',created_at:now,updated_at:now,
          parent_session_id:null,previous_session_id:null,completion_reason:null,model:'fixture',provider_id:'fixture'};
        window.findEvidence={keys:0,completed:0,prevented:false,writes:[],telemetry:[],requests:[]};
        window.addEventListener('keydown',event=>{
          if(event.key.toLowerCase()==='f'&&event.metaKey){
            const sequence=++window.findEvidence.keys;
            setTimeout(()=>{window.findEvidence.prevented=event.defaultPrevented;window.findEvidence.completed=sequence;},0);
          }
        });
        window.fetch=async(input,init)=>{
          const url=new URL(typeof input==='string'?input:input.url,location.origin), path=url.pathname;
          const method=init?.method||(typeof input==='string'?'GET':input.method)||'GET';
          window.findEvidence.requests.push(path);
          if(method==='POST'&&path==='/api/v1/chat/v2/client-performance') window.findEvidence.telemetry.push(method+' '+path);
          else if(method!=='GET') window.findEvidence.writes.push(method+' '+path);
          const user={email:'find@acceptance.invalid',name:'Find Acceptance',role:'admin'};
          let body={items:[],has_more:false,next_cursor:null};
          if(path.endsWith('/me')) body=user;
          else if(path.endsWith('/refresh')) body={status:'authenticated',user,expires_at:'2030-01-01T00:00:00Z'};
          else if(path==='/api/v1/user-preferences') body={display:{theme:'dark',language:'en',dashboard_workspace_windows:true},chat:{}};
          else if(path==='/api/v1/projects'||path==='/api/v1/notifications') body=[];
          else if(path==='/api/v1/agents') body={items:[agent],has_more:false,next_cursor:null};
          else if(path==='/api/v1/agents/agent-find') body=agent;
          else if(path==='/api/v1/library/agents') body=Array.from({length:7},(_,i)=>({agent_id:'agent-find-'+i,name:'Find Agent '+i,explicit:false,inherited:false,avatar_url:null}));
          else if(path==='/api/v1/conversations') body={items:[conversation],has_more:false,next_cursor:null};
          else if(path==='/api/v1/conversations/conv-find') body=conversation;
          else if(path==='/api/v1/conversations/conv-find/sessions') body=[session];
          else if(path==='/api/v1/sessions/sess-find') body=session;
          else if(path.endsWith('/opened')||path.endsWith('/read')) body={ok:true};
          else if(path.endsWith('/queue')) body={items:[],queued_count:0};
          else if(path==='/api/v1/conversations/waiting') body={conversations:{items:[],cursor:null,has_more:false},active_conversation_ids:[]};
          else if(path==='/api/v1/conversations/sidebar') body={agents:[agent],agent_direct_chats:[],background_work:{items:[]},conversations:{items:[conversation],has_more:false,next_cursor:null}};
          else if(path==='/api/v1/search/health') body={enabled:true};
          else if(path==='/api/v1/search/conversation/conv-find') body={matches:[],has_more:false,next_cursor:null};
          else if(path==='/api/v1/tasks/board') body={pending:[],running:[],paused:[],completed:[],failed:[],cancelled:[]};
          else if(path==='/api/v1/chat/v2/conversations/conv-find/snapshot') body={
            schema_version:2,projection_version:'find-native',scope:{key:'conversation:conv-find',kind:'conversation',conversation_id:'conv-find'},
            conversation,timeline:{items:[],has_more_before:false,before_cursor:null},
            state:{state_version:1,snapshot_generated_at:now,capabilities:[],active_turn:{},pending:{},
              active_session:{session_id:'sess-find',status:'active',completion_reason:null,todos:[]}},
            queue:{messages:[],queued_count:0},runtime:{runtime_epoch:'find-native',runtime_revision:1,generated_at:now,has_active_turn:false,volatile_items:[]},
            cursor:'cursor:conv-find',server_time:now};
          else if(path==='/api/v1/chat/v2/conversations/conv-find/sync') body={
            schema_version:2,projection_version:'find-native',scope:{key:'conversation:conv-find',kind:'conversation',conversation_id:'conv-find'},
            conversation_id:'conv-find',cursor_before:url.searchParams.get('cursor'),cursor_after:url.searchParams.get('cursor'),
            ops:[],runtime:null,reset_required:false,reset_reason:null,has_more:false,server_time:now};
          return new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}});
        };
        window.WebSocket=class extends EventTarget {
          static CONNECTING=0;static OPEN=1;static CLOSING=2;static CLOSED=3;readyState=0;
          constructor(){super();queueMicrotask(()=>{this.readyState=1;this.onopen?.(new Event('open'));});}
          send(){} close(){this.readyState=3;}
        };
        """

    private func open(_ path: String) throws -> (BundleWebView, NSWindow) {
        let root = try XCTUnwrap(ProcessInfo.processInfo.environment["COGNIS_FIND_WEB_ROOT"])
        let profile = try ServerProfile("https://find.acceptance.invalid",
            storageNamespace: "cz.fpy.cognis.tests.find." + UUID().uuidString)
        let host = try BundleWebView(profile: profile, root: URL(fileURLWithPath: root))
        host.web.configuration.userContentController.addUserScript(WKUserScript(
            source: fixture, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        let window = NSWindow(contentRect: NSRect(x: 100, y: 100, width: 1440, height: 1000),
            styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.contentView = host.web
        host.start(path: path)
        window.makeKeyAndOrderFront(nil)
        NSApplication.shared.activate(ignoringOtherApps: true)
        return (host, window)
    }

    private func close(_ host: BundleWebView, _ window: NSWindow) {
        host.web.stopLoading()
        window.contentView = nil
        window.close()
    }

    private func wait(_ host: BundleWebView, _ predicate: String) async throws {
        for _ in 0..<150 {
            if (try? await host.web.evaluateJavaScript(predicate)) as? Bool == true { return }
            try await Task.sleep(for: .milliseconds(50))
        }
        let info = try? await host.web.evaluateJavaScript(
            """
            JSON.stringify({errors:window.__cognisNativeStartupErrors,
              evidence:{keys:window.findEvidence.keys,completed:window.findEvidence.completed,prevented:window.findEvidence.prevented},active:document.activeElement?.tagName,
              viewport:{width:innerWidth,height:innerHeight},route:location.href,native:window.__cognisNative,
              dialogs:[...document.querySelectorAll('[role=dialog],dialog')].map(x=>({html:x.outerHTML.slice(0,500),rect:x.getBoundingClientRect().toJSON()})),
              search:[...document.querySelectorAll('button[aria-label="Search conversation"]')].map(x=>({
                rect:x.getBoundingClientRect().toJSON(),disabled:x.disabled,hidden:!!x.closest('[hidden],[inert],[aria-hidden="true"]'),
                ancestry:(()=>{const a=[];for(let p=x;p;p=p.parentElement){const s=getComputedStyle(p);a.push([p.tagName,s.display,s.visibility,p.hidden,p.inert,p.getAttribute('aria-hidden')]);}return a;})()
              }))})
            """)
        print("FIND_NATIVE_READINESS \(predicate): \(info ?? "no document")")
        throw NSError(domain: "FindReadiness", code: 1, userInfo: [
            NSLocalizedDescriptionKey: "Predicate \(predicate) failed: \(info ?? "no document")"])
    }

    private func key(_ window: NSWindow, characters: String = "f", code: UInt16 = 3, command: Bool = true) throws {
        let event = try XCTUnwrap(NSEvent.keyEvent(with: .keyDown, location: .zero,
            modifierFlags: command ? [.command] : [], timestamp: ProcessInfo.processInfo.systemUptime,
            windowNumber: window.windowNumber, context: nil, characters: characters,
            charactersIgnoringModifiers: characters, isARepeat: false, keyCode: code))
        XCTAssertFalse(NSApp.mainMenu?.performKeyEquivalent(with: event) ?? false)
        NSApp.sendEvent(event)
        let up = try XCTUnwrap(NSEvent.keyEvent(with: .keyUp, location: .zero,
            modifierFlags: command ? [.command] : [], timestamp: ProcessInfo.processInfo.systemUptime,
            windowNumber: window.windowNumber, context: nil, characters: characters,
            charactersIgnoringModifiers: characters, isARepeat: false, keyCode: code))
        NSApp.sendEvent(up)
    }

    private func state(_ host: BundleWebView) async throws -> String {
        try await host.web.evaluateJavaScript("""
            JSON.stringify({
              queries:[...document.querySelectorAll('input[type=search],input[placeholder="Search this conversation"]')].map(x=>x.value),
              drafts:[...document.querySelectorAll('textarea')].map(x=>x.value),
              results:[...(document.querySelector('input[placeholder="Search this conversation"]')?.closest('form')?.querySelectorAll('button:not([aria-label])')??[])].map(x=>[x.textContent,x.className]),
              writes:window.findEvidence.writes
            })
            """) as? String ?? ""
    }

    private func chatPreservation(_ host: BundleWebView) async throws -> String {
        try await host.web.evaluateJavaScript("""
            JSON.stringify({
              query:document.querySelector('input[placeholder="Search this conversation"]')?.value??'',
              drafts:[...document.querySelectorAll('textarea')].map(x=>x.value),
              results:[...(document.querySelector('input[placeholder="Search this conversation"]')?.closest('form')?.querySelectorAll('button:not([aria-label])')??[])].map(x=>[x.textContent,x.className]),
              writes:window.findEvidence.writes,
              searches:window.findEvidence.requests.filter(x=>x==='/api/v1/search/conversation/conv-find').length
            })
            """) as? String ?? ""
    }

    func testCompiledChatCollapsedAndRepeatedFind() async throws {
        let app = NSApplication.shared, previous = NSApp.mainMenu
        app.mainMenu = applicationMenu(application: NSMenu(title: "Cognis Acceptance"))
        defer { app.mainMenu = previous }
        let (host, window) = try open("/chat/conv-find")
        defer { close(host, window) }
        try await wait(host, "document.querySelector('button[aria-label=\"Search conversation\"]')?.disabled===false && !!document.querySelector('textarea')")
        let preKeyEnabled = try await host.web.evaluateJavaScript(
            "document.querySelector('button[aria-label=\"Search conversation\"]')?.disabled===false") as? Bool
        XCTAssertEqual(preKeyEnabled, true)
        print("FIND_NATIVE_CHAT_PRE_KEY enabled=\(preKeyEnabled == true)")
        _ = try await host.web.evaluateJavaScript("""
            (()=>{const draft=document.querySelector('textarea');draft.value='unsent native draft';
            draft.dispatchEvent(new Event('input',{bubbles:true}));draft.focus();return true;})()
            """)
        XCTAssertTrue(window.makeFirstResponder(host.web))
        let beforeFirst = try await chatPreservation(host)
        try key(window)
        try await wait(host, "document.activeElement?.placeholder==='Search this conversation' && window.findEvidence.completed===1 && window.findEvidence.prevented")
        let afterFirst = try await chatPreservation(host)
        XCTAssertEqual(afterFirst, beforeFirst)
        _ = try await host.web.evaluateJavaScript("""
            (()=>{const input=document.querySelector('input[placeholder="Search this conversation"]');input.value='retained';
            input.dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('textarea').focus();return true;})()
            """)
        let before = try await state(host)
        try key(window)
        try await wait(host, "document.activeElement?.placeholder==='Search this conversation' && document.activeElement.selectionEnd===8 && window.findEvidence.completed===2 && window.findEvidence.prevented")
        let after = try await state(host)
        XCTAssertEqual(after, before)
        let selected = try await host.web.evaluateJavaScript("document.activeElement.selectionStart") as? Int
        XCTAssertEqual(selected, 0)
        print("FIND_NATIVE_CHAT \(after)")
    }

    func testCompiledNestedDialogsAndNoEligibleTarget() async throws {
        let app = NSApplication.shared, previous = NSApp.mainMenu
        app.mainMenu = applicationMenu(application: NSMenu(title: "Cognis Acceptance"))
        defer { app.mainMenu = previous }
        let (host, window) = try open("/library")
        defer { close(host, window) }
        try await wait(host, "!![...document.querySelectorAll('button')].find(x=>x.textContent.includes('New artifact'))")
        _ = try await host.web.evaluateJavaScript("[...document.querySelectorAll('button')].find(x=>x.textContent.includes('New artifact')).click();true")
        try await wait(host, "!!document.querySelector('[data-testid=\"new-artifact-modal\"]')")
        let before = try await state(host)
        XCTAssertTrue(window.makeFirstResponder(host.web))
        try key(window)
        try await wait(host, "window.findEvidence.completed===1")
        let blocked = try await host.web.evaluateJavaScript("!window.findEvidence.prevented && document.activeElement!==document.querySelector('input[type=search]')") as? Bool
        XCTAssertEqual(blocked, true)
        _ = try await host.web.evaluateJavaScript("document.querySelector('button[aria-label=\"Select agents\"]').click();true")
        try await wait(host, "!!document.querySelector('input[aria-label=\"Find agents\"]')")
        try key(window)
        try await wait(host, "document.activeElement?.getAttribute('aria-label')==='Find agents' && window.findEvidence.completed===2 && window.findEvidence.prevented")
        let after = try await state(host)
        XCTAssertEqual(after, before)
        print("FIND_NATIVE_DIALOGS searchless-default-preserved; nested-search-focused")
    }

    func testTwoNativeDocumentsHiddenMinimizedAndInactiveIsolation() async throws {
        let app = NSApplication.shared, previous = NSApp.mainMenu
        app.mainMenu = applicationMenu(application: NSMenu(title: "Cognis Acceptance"))
        defer { app.mainMenu = previous }
        let (first, firstWindow) = try open("/library")
        defer { close(first, firstWindow) }
        try await wait(first, "!!document.querySelector('input[type=search]')")
        let (second, secondWindow) = try open("/library")
        defer { close(second, secondWindow) }
        try await wait(second, "!!document.querySelector('input[type=search]')")
        let before = try await state(first)
        for mode in ["inactive", "hidden", "minimized"] {
            firstWindow.deminiaturize(nil)
            firstWindow.orderFront(nil)
            if mode == "hidden" { firstWindow.orderOut(nil) }
            if mode == "minimized" { firstWindow.miniaturize(nil) }
            secondWindow.makeKeyAndOrderFront(nil)
            XCTAssertTrue(secondWindow.makeFirstResponder(second.web))
            let count = try await second.web.evaluateJavaScript("window.findEvidence.keys") as? Int ?? 0
            try key(secondWindow)
            try await wait(second, "window.findEvidence.completed===\(count + 1) && window.findEvidence.keys===\(count + 1) && window.findEvidence.prevented && document.activeElement?.type==='search' && document.activeElement.selectionStart===0 && document.activeElement.selectionEnd===document.activeElement.value.length")
            let firstKeys = try await first.web.evaluateJavaScript("window.findEvidence.keys") as? Int
            let firstState = try await state(first)
            XCTAssertEqual(firstKeys, 0)
            XCTAssertEqual(firstState, before)
            print("FIND_NATIVE_ISOLATION \(mode)")
        }
    }

    func testCompiledDashboardCompactWindowFallbackAndMinimize() async throws {
        let app = NSApplication.shared, previous = NSApp.mainMenu
        app.mainMenu = applicationMenu(application: NSMenu(title: "Cognis Acceptance"))
        defer { app.mainMenu = previous }
        let (host, window) = try open("/")
        defer { close(host, window) }
        try await wait(host, "!!document.querySelector('[data-testid=\"dashboard-conversation-row-conv-find\"]')")
        _ = try await host.web.evaluateJavaScript("document.querySelector('[data-testid=\"dashboard-conversation-row-conv-find\"]').click();true")
        try await wait(host, "!!document.querySelector('[data-window-key][data-focused=\"true\"] textarea')")
        _ = try await host.web.evaluateJavaScript("document.querySelector('[data-window-key][data-focused=\"true\"] textarea').focus();true")
        let before = try await state(host)
        XCTAssertTrue(window.makeFirstResponder(host.web))
        try key(window)
        try await wait(host, "document.activeElement?.getAttribute('aria-label')==='Search tasks and conversations' && window.findEvidence.completed===1 && window.findEvidence.keys===1 && window.findEvidence.prevented && document.activeElement.selectionStart===0 && document.activeElement.selectionEnd===document.activeElement.value.length")
        let after = try await state(host)
        XCTAssertEqual(after, before)
        _ = try await host.web.evaluateJavaScript("document.querySelector('[data-window-key][data-focused=\"true\"] button[aria-label=\"Minimize\"]').click();true")
        try key(window)
        try await wait(host, "document.activeElement?.getAttribute('aria-label')==='Search tasks and conversations' && window.findEvidence.completed===2 && window.findEvidence.keys===2 && window.findEvidence.prevented && document.activeElement.selectionStart===0 && document.activeElement.selectionEnd===document.activeElement.value.length")
        print("FIND_NATIVE_DASHBOARD compact-fallback-and-minimize")
    }

    func testCompiledLibraryFindThroughApplicationResponder() async throws {
        let root = try XCTUnwrap(ProcessInfo.processInfo.environment["COGNIS_FIND_WEB_ROOT"])
        let app = NSApplication.shared
        let previousMenu = app.mainMenu
        // Production Edit/Window responder menus, without launching account services.
        app.mainMenu = applicationMenu(application: NSMenu(title: "Cognis Acceptance"))
        defer { app.mainMenu = previousMenu }
        let profile = try ServerProfile("https://find.acceptance.invalid",
            storageNamespace: "cz.fpy.cognis.tests.find." + UUID().uuidString)
        let host = try BundleWebView(profile: profile, root: URL(fileURLWithPath: root))
        host.web.configuration.userContentController.addUserScript(WKUserScript(source: """
            window.findEvidence = {keys:0, prevented:false, writes:0};
            window.addEventListener('keydown', event => {
              if (event.key.toLowerCase() === 'f' && event.metaKey) {
                window.findEvidence.keys++;
                // WebKit may checkpoint microtasks between native-dispatched listeners.
                // Observe cancellation after the complete event dispatch.
                setTimeout(() => window.findEvidence.prevented = event.defaultPrevented, 0);
              }
            });
            window.fetch = async (input, init) => {
              const path = new URL(typeof input === 'string' ? input : input.url, location.origin).pathname;
              if (init?.method && init.method !== 'GET') window.findEvidence.writes++;
              const user = {email:'find@acceptance.invalid',name:'Find Acceptance',role:'admin'};
              let body = {items:[],has_more:false,next_cursor:null};
              if (path.endsWith('/me')) body = user;
              else if (path.endsWith('/refresh')) body = {status:'authenticated',user,expires_at:'2030-01-01T00:00:00Z'};
              else if (path.endsWith('/projects')) body = [];
              else if (path.endsWith('/user-preferences')) body = {display:{theme:'dark',language:'en'}};
              return new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}});
            };
            window.WebSocket = class extends EventTarget {
              static CONNECTING=0; static OPEN=1; static CLOSING=2; static CLOSED=3;
              readyState=0;
              constructor() {super();queueMicrotask(()=>{this.readyState=1;this.onopen?.(new Event('open'));});}
              send() {} close() {this.readyState=3;}
            };
            """, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        let window = NSWindow(contentRect: NSRect(x: 100, y: 100, width: 1200, height: 900),
            styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.contentView = host.web
        defer { host.web.stopLoading(); window.contentView = nil; window.close() }
        host.start(path: "/library")
        window.makeKeyAndOrderFront(nil)
        app.activate(ignoringOtherApps: true)
        var ready = false
        for _ in 0..<150 {
            ready = (try? await host.web.evaluateJavaScript(
                "!!document.querySelector('input[type=search]')")) as? Bool ?? false
            if ready { break }
            try await Task.sleep(for: .milliseconds(50))
        }
        guard ready else {
            let diagnostic = try? await host.web.evaluateJavaScript(
                "JSON.stringify({url:location.href,text:document.body.innerText.slice(0,1500),errors:window.__cognisNativeStartupErrors})")
            XCTFail("Compiled library not ready: \(diagnostic ?? "no document")")
            return
        }
        // Test setup only: no synthetic keyboard event or product handler invocation.
        let before = try await host.web.evaluateJavaScript("""
            (() => { const input=document.querySelector('input[type=search]');
              input.value='retained query'; input.blur();
              return window.findEvidence.writes; })()
            """) as? Int
        XCTAssertTrue(window.makeFirstResponder(host.web))
        let event = try XCTUnwrap(NSEvent.keyEvent(with: .keyDown, location: .zero,
            modifierFlags: [.command], timestamp: ProcessInfo.processInfo.systemUptime,
            windowNumber: window.windowNumber, context: nil, characters: "f",
            charactersIgnoringModifiers: "f", isARepeat: false, keyCode: 3))
        let intercepted = app.mainMenu?.performKeyEquivalent(with: event) ?? false
        print("FIND_NATIVE_MENU_INTERCEPTED \(intercepted)")
        XCTAssertFalse(intercepted)
        app.sendEvent(event)
        var evidence: [String: Any] = [:]
        for _ in 0..<100 {
            evidence = try await host.web.evaluateJavaScript("""
                (() => { const input=document.querySelector('input[type=search]');
                  return {...window.findEvidence,focused:document.activeElement===input,
                    value:input.value,start:input.selectionStart,end:input.selectionEnd}; })()
                """) as? [String: Any] ?? [:]
            if evidence["focused"] as? Bool == true && evidence["prevented"] as? Bool == true { break }
            try await Task.sleep(for: .milliseconds(50))
        }
        print("FIND_NATIVE_DOM \(evidence)")
        XCTAssertEqual(evidence["keys"] as? Int, 1)
        XCTAssertEqual(evidence["prevented"] as? Bool, true)
        XCTAssertEqual(evidence["focused"] as? Bool, true)
        XCTAssertEqual(evidence["value"] as? String, "retained query")
        XCTAssertEqual(evidence["start"] as? Int, 0)
        XCTAssertEqual(evidence["end"] as? Int, 14)
        XCTAssertEqual(evidence["writes"] as? Int, before)
    }
}
