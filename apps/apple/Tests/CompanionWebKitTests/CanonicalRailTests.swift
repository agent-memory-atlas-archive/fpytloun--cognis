import XCTest
import AppKit
import WebKit
import CoreGraphics
import CompanionContract
@testable import CognisCompanion

@MainActor
final class CanonicalRailTests: XCTestCase {
    private let fixture = """
    (() => {
      if (!location.hostname.endsWith('.invalid')) throw Error('Synthetic HTTPS origin required');
      const avatar = color => 'data:image/svg+xml,' + encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512"><rect width="512" height="512" fill="'+color+'"/><circle cx="256" cy="192" r="100" fill="#f1ca9a"/><path d="M70 512V410a186 186 0 0 1 372 0v102" fill="#173b55"/><path d="M256 0v512M0 256h512" stroke="#fff" stroke-opacity=".18" stroke-width="2"/></svg>');
      const agents = [
        {agent_id:'agent_first',name:'Synthetic First',avatar_url:avatar('#426d85')},
        {agent_id:'agent_second',name:'Synthetic Second',avatar_url:avatar('#785e90')}
      ];
      window.fetch = async input => {
        const path = new URL(typeof input === 'string' ? input : input.url, location.origin).pathname;
        const user = {email:'rail@fixture.invalid',name:'Synthetic Rail',role:'user'};
        let body = {};
        if (path.endsWith('/me')) body = user;
        else if (path.endsWith('/refresh') || path.endsWith('/logout')) body={status:'authenticated',user,expires_at:'2030-01-01T00:00:00Z'};
        else if (path.includes('preferences')) body={display:{dashboard_workspace_windows:true,pinned_agents_collapsed:false}};
        else if (/\\/conversations\\/conv_(first|second)$/.test(path)) {
          const id=path.split('/').pop(), first=id==='conv_first';
          body={conversation_id:id,agent_id:first?'agent_first':'agent_second',title:'Synthetic chat',status:first?'active':'idle',has_active_turn:first,has_unread:!first,context:{type:'web'}};
        } else if (path.includes('/agents')) body={items:agents,has_more:false};
        else if (path.includes('/sidebar')) body={background_work:{items:[]},agent_direct_chats:[]};
        else if (path.includes('/inbox')) body={items:[],total:0,unread_count:0};
        return new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}});
      };
      window.WebSocket=class extends EventTarget {
        static CONNECTING=0; static OPEN=1; static CLOSING=2; static CLOSED=3; readyState=0;
        constructor(){super();queueMicrotask(()=>{this.readyState=1;this.onopen?.(new Event('open'));});}
        send(){} close(){this.readyState=3;}
      };
      window.EventSource=class {close(){} addEventListener(){} removeEventListener(){}};
    })();
    """
    private func wait(_ host: BundleWebView, _ predicate: String) async throws {
        for _ in 0..<200 {
            if try await host.web.evaluateJavaScript(predicate) as? Bool == true { return }
            try await Task.sleep(for: .milliseconds(50))
        }
        print("RAIL_WAIT_TIMEOUT: \(predicate)")
        if let window = host.web.window { try? await geometryDiagnostic(host, window: window, label: "timeout") }
        throw NSError(domain: "CanonicalRail", code: 1, userInfo: [NSLocalizedDescriptionKey: predicate])
    }
    private func geometryDiagnostic(_ host: BundleWebView, window: NSWindow, label: String) async throws {
        let tuple = try await host.web.evaluateJavaScript("""
        JSON.stringify((() => {
          const dock=document.querySelector('.native-dock'), column=document.querySelector('.native-column');
          const face=column?.querySelector('.avatar-face'), style=face && getComputedStyle(face);
          const rect=node => node ? ({x:node.getBoundingClientRect().x,y:node.getBoundingClientRect().y,
            width:node.getBoundingClientRect().width,height:node.getBoundingClientRect().height,
            right:node.getBoundingClientRect().right,bottom:node.getBoundingClientRect().bottom}) : null;
          return {tucked:dock?.dataset.tucked,visuallyTucked:dock?.dataset.visuallyTucked,
            selected:[...document.querySelectorAll('[data-selected=true]')].map(n=>n.dataset.pinnedAgent),
            pointer:[...document.querySelectorAll('[data-native-hover=true]')].map(n=>n.dataset.pinnedAgent),
            left:!!document.querySelector('.native-left'),transform:style?.transform,
            transition:style?.transition,reducedMotion:matchMedia('(prefers-reduced-motion: reduce)').matches,
            rootFont:getComputedStyle(document.documentElement).fontSize,
            viewport:{width:innerWidth,height:innerHeight},column:rect(column),face:rect(face),
            visibility:document.visibilityState};
        })())
        """)
        print("RAIL_GEOMETRY \(label): visible=\(window.isVisible) occlusion=\(window.occlusionState.rawValue) appHidden=\(NSApp.isHidden) appActive=\(NSApp.isActive) policy=\(NSApp.activationPolicy().rawValue) \(String(describing: tuple))")
    }
    func testActualSharedRailAndOriginalImageSnapshots() async throws {
        try await exerciseRail(reducedMotion: true)
    }
    func testAttachedRailMotionAndDefaultHalfHide() async throws {
        try await exerciseRail(reducedMotion: false)
    }
    private func exerciseRail(reducedMotion: Bool) async throws {
        guard let root = ProcessInfo.processInfo.environment["COGNIS_WORKSPACE_WEB_ROOT"] else {
            throw XCTSkip("Opt in with the isolated test-only application export")
        }
        let previousPolicy = NSApplication.shared.activationPolicy()
        defer { if !reducedMotion { NSApp.setActivationPolicy(previousPolicy) } }
        let profile = try ServerProfile("https://rail-\(UUID().uuidString.lowercased()).invalid",
                                        storageNamespace: "cz.fpy.cognis.rail-test")
        var hosts: [BundleWebView] = [], windows: [NSWindow] = []
        var relay: WorkspaceRelay?
        var opened: [String] = []
        func make(_ surface: String, path: String, width: CGFloat) throws -> BundleWebView {
            let host = try BundleWebView(profile: profile, root: URL(fileURLWithPath: root), surface: surface)
             host.web.configuration.userContentController.addUserScript(
                 WKUserScript(source: fixture, injectionTime: .atDocumentStart, forMainFrameOnly: true))
             if reducedMotion {
                 // Local fixture only, not an OS accessibility preference. Normal
                 // motion is exercised in a separate attached-window invocation.
                 host.web.configuration.userContentController.addUserScript(WKUserScript(source: """
                 const systemMatchMedia=window.matchMedia.bind(window);
                 window.matchMedia=query => query === '(prefers-reduced-motion: reduce)'
                   ? {matches:true,media:query,onchange:null,addEventListener(){},removeEventListener(){},
                      addListener(){},removeListener(){},dispatchEvent(){return true;}}
                   : systemMatchMedia(query);
                 """, injectionTime: .atDocumentStart, forMainFrameOnly: true))
             }
            let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: width, height: 700),
                styleMask: [.titled, .closable], backing: .buffered, defer: false)
            window.isReleasedWhenClosed = false
            if surface == "conversation" {
                window.styleMask.insert(.fullSizeContentView)
                window.titleVisibility = .hidden; window.titlebarAppearsTransparent = true
                window.contentView = WindowSurface(web: host.web, main: true)
            } else { window.contentView = host.web }
            hosts.append(host); windows.append(window)
            host.onMessage = { [weak host] message in
                guard let host else { return }
                if case .railSize(let width, let height) = message, surface == "rail" {
                    window.setContentSize(NSSize(width: width, height: height))
                }
                if case .rail("open", let id, _) = message, let id { opened.append(id) }
                guard case .workspace(let frame) = message else { return }
                let targets = relay?.route(frame, source: host.generation, documents: Set(hosts.map(\.generation))) {
                    for value in hosts where value !== hosts.first { value.send(["type": "workspace-reset"]) }
                } ?? []
                for value in hosts where targets.contains(value.generation) {
                    value.send(["type": "workspace", "frame": frame.value])
                }
            }
            host.start(path: path)
            return host
        }
        let main = try make("main", path: "/workspace-acceptance?rail=browser", width: 900)
        relay = WorkspaceRelay(profile: profile.origin.absoluteString, main: main.generation)
        let rail = try make("rail", path: "/native-rail", width: 64)
         let standalone = try make("conversation", path: "/chat/conv_first", width: 900)
        defer { hosts.forEach { $0.invalidate() }; windows.forEach { $0.contentView = nil; $0.close() } }
         try await wait(main, "document.getElementById('auth-state')?.textContent === 'authenticated'")
         for host in hosts {
             // Canonical geometry at the nominal 16 px text scale. Real user
             // density may be 15 px; the shared rem anchor scales with it.
             _ = try await host.web.evaluateJavaScript("document.documentElement.style.fontSize='16px'")
         }
          if !reducedMotion {
              // XCTest is normally a background application. Only this test
              // process becomes a visible UI host; no system preference changes.
              NSApp.setActivationPolicy(.regular)
              NSApp.unhide(nil)
              windows[1].makeKeyAndOrderFront(nil)
              NSApp.activate()
              try await wait(rail, "document.visibilityState === 'visible'")
         }
        for id in ["pin-first", "pin-second"] {
            _ = try await main.web.callAsyncJavaScript("document.getElementById(id).click()", arguments: ["id": id], in: nil, contentWorld: .page)
        }
        let avatars = "document.querySelectorAll('[data-pinned-agent]').length === 2"
        try await wait(rail, avatars); try await wait(main, avatars)
        // Unset now defaults to half-hide. Explicitly reveal for the geometry
        // and pointer cases, then exercise half-hide separately below.
         try await wait(rail, "document.querySelector('[data-visually-tucked=true]') !== null")
         try await wait(rail, """
         (() => {const face=document.querySelector('.avatar-face'), transform=getComputedStyle(face).transform;
           return transform !== 'none' && Math.abs(new DOMMatrix(transform).m41-40)<0.1;})()
         """)
         try await geometryDiagnostic(rail, window: windows[1], label: "default right half-hide")
         let exposed = try await rail.web.evaluateJavaScript("innerWidth-document.querySelector('.avatar-face').getBoundingClientRect().left") as? Double
         XCTAssertEqual(try XCTUnwrap(exposed), 24, accuracy: 0.5, "Unset preference exposes exactly half the 48 px circle")
         rail.send(["type": "rail-tuck"])
         try await wait(rail, "document.querySelector('[data-visually-tucked=false]') !== null")
         try await wait(rail, """
         [...document.querySelectorAll('.avatar-face')].every(face => {
           const transform=getComputedStyle(face).transform;
           return transform === 'none' || Math.abs(new DOMMatrix(transform).m41)<0.1;
         })
         """)
        for host in [main, rail] {
            try await wait(host, "Array.from(document.querySelectorAll('.avatar-face img')).every(i => i.complete && i.naturalWidth === 512)")
            let selected = try await host.web.evaluateJavaScript("document.querySelectorAll('[data-selected=true]').length") as? Int
            XCTAssertEqual(selected, 0)
        }
        _ = try await rail.web.evaluateJavaScript("document.querySelector('[data-pinned-agent=agent_first]').click()")
        for _ in 0..<100 {
            if !opened.isEmpty { break }
            try await Task.sleep(for: .milliseconds(50))
        }
        XCTAssertEqual(opened, ["agent_first"])
        // Inject AppKit events into this fixture's actual WK hit-test target.
        // This is native-to-WebKit delivery in an attached inactive test window,
        // not a claim of physical desktop/focus acceptance.
        let rawPoint = try await rail.web.evaluateJavaScript("""
        (() => { const r=document.querySelector('[data-pinned-agent=agent_first]').getBoundingClientRect();
          return {x:r.x+r.width/2,y:r.y+r.height/2}; })()
        """)
        let point = try XCTUnwrap(rawPoint as? [String: Double])
        let local = NSPoint(x: point["x"]!, y: rail.web.isFlipped ? point["y"]! : rail.web.bounds.height - point["y"]!)
        let windowPoint = rail.web.convert(local, to: nil)
        let target = try XCTUnwrap(rail.web.hitTest(local))
        for type in [NSEvent.EventType.leftMouseDown, .leftMouseUp] {
            let event = try XCTUnwrap(NSEvent.mouseEvent(with: type, location: windowPoint,
                modifierFlags: [], timestamp: ProcessInfo.processInfo.systemUptime,
                windowNumber: windows[1].windowNumber, context: nil, eventNumber: 1,
                clickCount: 1, pressure: type == .leftMouseDown ? 1 : 0))
            if type == .leftMouseDown { target.mouseDown(with: event) } else { target.mouseUp(with: event) }
        }
        for _ in 0..<100 {
            if opened.count >= 2 { break }
            try await Task.sleep(for: .milliseconds(50))
        }
        XCTAssertEqual(opened, ["agent_first", "agent_first"], "One native mouse gesture must issue exactly one open command")
        rail.send(["type": "rail-state", "selectedAgentId": "agent_first", "side": "right"])
        try await wait(rail, "document.querySelectorAll('[data-selected=true]').length === 1")
        rail.send(["type": "rail-state", "selectedAgentId": NSNull(), "side": "left"])
        try await wait(rail, "document.querySelectorAll('[data-selected=true]').length === 0")
        // Exercise the real scrollport, not CSS-source assertions. Both endpoints
        // must retain room for the canonical shadow/orbit even when scrolling.
        let naturalRailSize = rail.web.bounds.size
        for side in ["left", "right"] {
            windows[1].setContentSize(NSSize(width: rail.web.bounds.width, height: 90))
            try await wait(rail, "document.querySelector('.native-column').scrollHeight > document.querySelector('.native-column').clientHeight")
            for state in ["activity", "selected", "hover"] {
                rail.send(["type": "rail-state", "selectedAgentId": state == "selected" ? "agent_first" as Any : NSNull(),
                           "side": side, "pointerInside": false])
                 try await wait(rail, "document.querySelector('.native-left') \(side == "left" ? "!==" : "===") null")
                 try await wait(rail, """
                 [...document.querySelectorAll('.avatar-face')].every(face => {
                   const transform=getComputedStyle(face).transform;
                   return transform === 'none' || Math.abs(new DOMMatrix(transform).m41)<0.1;
                 })
                 """)
                if state == "hover" {
                    _ = try await rail.web.evaluateJavaScript("""
                    document.querySelector('[data-pinned-agent=agent_second]')
                      .dispatchEvent(new PointerEvent('pointerenter',{pointerType:'mouse'}))
                    """)
                    try await wait(rail, "document.querySelector('[data-native-hover=true]') !== null")
                }
                let padded = try await rail.web.evaluateJavaScript("""
                (() => {
                  const column=document.querySelector('.native-column');
                  return ['firstElementChild','lastElementChild'].every(key => {
                    column.scrollTop = key === 'firstElementChild' ? 0 : column.scrollHeight;
                    const viewport=column.getBoundingClientRect();
                    const face=column[key].querySelector('.avatar-face').getBoundingClientRect();
                    return face.top-viewport.top >= 8 && viewport.bottom-face.bottom >= 8
                      && face.left-viewport.left >= 8 && viewport.right-face.right >= 8;
                  });
                })()
                """) as? Bool
                 try await geometryDiagnostic(rail, window: windows[1], label: "\(side) \(state) halo")
                 XCTAssertEqual(padded, true, "\(side) \(state): first/last halo padding")
                let edge = try await rail.web.evaluateJavaScript("""
                (() => {
                  const face=document.querySelector('.avatar-face').getBoundingClientRect();
                  return \(side == "left" ? "face.left" : "innerWidth-face.right");
                })()
                """) as? Double
                 try await geometryDiagnostic(rail, window: windows[1], label: "\(side) \(state) edge")
                 XCTAssertEqual(try XCTUnwrap(edge), 16, accuracy: 0.5, "\(side) visible circle, not halo canvas")
         if reducedMotion, let output = ProcessInfo.processInfo.environment["COGNIS_RAIL_SCREENSHOTS"] {
                    let directory = URL(fileURLWithPath: output)
                    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
                    for endpoint in ["first", "last"] {
                      let agent = endpoint == "first" ? "agent_first" : "agent_second"
                      rail.send(["type": "rail-state", "selectedAgentId": state == "selected" ? agent as Any : NSNull(),
                                 "side": side, "pointerInside": false])
                      _ = try await rail.web.evaluateJavaScript("""
                      (() => {
                      const column=document.querySelector('.native-column');
                      column.scrollTop = \(endpoint == "first" ? "0" : "column.scrollHeight");
                      document.querySelectorAll('[data-pinned-agent]').forEach(item =>
                        item.dispatchEvent(new PointerEvent('pointerleave',{pointerType:'mouse'})));
                      })()
                      """)
                      if state == "hover" {
                        _ = try await rail.web.evaluateJavaScript("""
                        document.querySelector('[data-pinned-agent=\(agent)]')
                          .dispatchEvent(new PointerEvent('pointerenter',{pointerType:'mouse'}))
                        """)
                      }
                      // Occluded macOS windows can suspend requestAnimationFrame.
                      // Never await an unbounded page promise just to paint a snapshot.
                      try await Task.sleep(for: .milliseconds(100))
                      for scale in [1, 2] {
                        let options = WKSnapshotConfiguration()
                        // WK rounds snapshotWidth to whole points before applying
                        // display scale. Keep both 1x and 2x requests integral.
                        let backingScale = windows[1].backingScaleFactor
                        let width = floor(rail.web.bounds.width / backingScale) * backingScale
                        options.rect = NSRect(x: 0, y: 0, width: width, height: rail.web.bounds.height)
                        let pixels = Int(width) * scale
                        options.snapshotWidth = NSNumber(value: Double(pixels) / backingScale)
                        let image = try await rail.web.takeSnapshot(configuration: options)
                        let bitmap = try XCTUnwrap(image.tiffRepresentation.flatMap { NSBitmapImageRep(data: $0) })
                        let png = try XCTUnwrap(bitmap.representation(using: .png, properties: [:]))
                        XCTAssertEqual(bitmap.pixelsWide, pixels, "Snapshot must have the labelled physical resolution")
                        try png.write(to: directory.appendingPathComponent("padded-\(side)-\(state)-\(endpoint)-\(scale)x.png"))
                      }
                    }
                }
            }
        }
        windows[1].setContentSize(naturalRailSize)
         if reducedMotion, let output = ProcessInfo.processInfo.environment["COGNIS_RAIL_SCREENSHOTS"] {
            let directory = URL(fileURLWithPath: output)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            for (index, host) in [main, rail].enumerated() {
                for (name, appearance) in [("light", NSAppearance.Name.aqua), ("dark", .darkAqua)] {
                    windows[index].appearance = NSAppearance(named: appearance)
                    _ = try await host.web.evaluateJavaScript("document.documentElement.style.colorScheme='\(name)'; document.documentElement.style.setProperty('--theme-obsidian','\(name == "light" ? "#f8fafc" : "#07111a")')")
                    for scale in [1, 2] {
                        let options = WKSnapshotConfiguration()
                        let width = rail.web.bounds.width
                        options.rect = NSRect(x: index == 0 ? 900 - width : 0, y: 0, width: width, height: 700)
                        options.snapshotWidth = NSNumber(value: Double(width * CGFloat(scale)) / windows[index].backingScaleFactor)
                        let image = try await host.web.takeSnapshot(configuration: options)
                        guard let data = image.tiffRepresentation,
                              let bitmap = NSBitmapImageRep(data: data),
                              let png = bitmap.representation(using: .png, properties: [:]) else { return XCTFail("Snapshot encoding failed") }
                        try png.write(to: directory.appendingPathComponent("\(index == 0 ? "browser" : "native")-\(name)-\(scale)x.png"))
                        print("RAIL_SNAPSHOT \(index) \(name) requested=\(scale)x pixels=\(bitmap.pixelsWide)x\(bitmap.pixelsHigh) displayScale=\(windows[index].backingScaleFactor)")
                    }
                }
            }
            // Actual WK standalone document, same titlebar inset/surface as main;
            // no screenshot permissions, OS focus claim or production API used.
            let standaloneWindow = windows[2]
            XCTAssertTrue(standaloneWindow.styleMask.contains(.titled))
            XCTAssertNotNil(standaloneWindow.standardWindowButton(.closeButton))
            XCTAssertEqual(standalone.web.frame.minY, 0)
            for (name, appearance) in [("light", NSAppearance.Name.aqua), ("dark", .darkAqua)] {
                standaloneWindow.appearance = NSAppearance(named: appearance)
                standaloneWindow.backgroundColor = name == "light" ? .white : NSColor(red: 7/255, green: 17/255, blue: 26/255, alpha: 1)
                standaloneWindow.contentView?.layer?.backgroundColor = standaloneWindow.backgroundColor.cgColor
                _ = try await standalone.web.evaluateJavaScript("document.documentElement.style.colorScheme='\(name)'; document.documentElement.style.setProperty('--theme-obsidian','\(name == "light" ? "#ffffff" : "#07111a")')")
                for scale in [1, 2] {
                    let options = WKSnapshotConfiguration()
                    options.snapshotWidth = NSNumber(value: Double(900 * scale) / standaloneWindow.backingScaleFactor)
                    let image = try await standalone.web.takeSnapshot(configuration: options)
                    let bitmap = try XCTUnwrap(image.tiffRepresentation.flatMap { NSBitmapImageRep(data: $0) })
                    XCTAssertEqual(bitmap.pixelsWide, 900 * scale)
                    let png = try XCTUnwrap(bitmap.representation(using: .png, properties: [:]))
                    try png.write(to: directory.appendingPathComponent("standalone-\(name)-\(scale)x.png"))
                }
            }
            rail.send(["type": "rail-tuck"])
            try await wait(rail, "document.querySelector('[data-visually-tucked=true]') !== null")
            for scenario in ["half-hidden", "hover-revealed"] {
                if scenario == "hover-revealed" {
                    _ = try await rail.web.evaluateJavaScript("const strip=document.querySelector('[data-visually-tucked]'); strip.dispatchEvent(new PointerEvent('pointerleave',{pointerType:'mouse'})); strip.dispatchEvent(new PointerEvent('pointerenter',{pointerType:'mouse'}))")
                    try await wait(rail, "document.querySelector('[data-visually-tucked=false]') !== null")
                }
                // Offscreen WK composition can suspend transition clocks. These
                // are final-state snapshots, not animation timing acceptance.
                _ = try await rail.web.evaluateJavaScript(
                    "document.querySelectorAll('[data-testid=pinned-avatar-face]').forEach(face => {getComputedStyle(face).transform; face.getAnimations().forEach(animation => animation.finish());})")
                let shifted = try await rail.web.evaluateJavaScript(
                    "Array.from(document.querySelectorAll('[data-testid=pinned-avatar-face]')).every(face => Math.abs(new DOMMatrixReadOnly(getComputedStyle(face).transform).m41) > 1)") as? Bool
                XCTAssertEqual(shifted, scenario == "half-hidden")
                let options = WKSnapshotConfiguration()
                options.rect = NSRect(x: 0, y: 0, width: 64, height: 240)
                options.snapshotWidth = 128
                let image = try await rail.web.takeSnapshot(configuration: options)
                guard let data = image.tiffRepresentation, let bitmap = NSBitmapImageRep(data: data),
                      let png = bitmap.representation(using: .png, properties: [:])
                else { return XCTFail("Snapshot encoding failed") }
                try png.write(to: directory.appendingPathComponent("native-\(scenario)-2x.png"))
            }
            rail.send(["type": "rail-tuck"])
            try await wait(rail, "document.querySelector('[data-visually-tucked=false]') !== null")
        }
        if !reducedMotion {
            // Normal 220 ms motion in a visible, attached, app-owned WK window.
            rail.send(["type": "rail-tuck"])
            try await wait(rail, "document.querySelector('[data-visually-tucked=true]') !== null")
            try await wait(rail, "Math.abs(new DOMMatrix(getComputedStyle(document.querySelector('.avatar-face')).transform).m41-40)<0.1")
            rail.send(["type": "rail-state", "pointerInside": true, "selectedAgentId": "agent_first", "side": "right"])
            try await wait(rail, "document.querySelector('[data-visually-tucked=false]') !== null")
            try await wait(rail, "Math.abs(new DOMMatrix(getComputedStyle(document.querySelector('.avatar-face')).transform).m41)<0.1")
            rail.send(["type": "rail-state", "pointerInside": false, "selectedAgentId": NSNull(), "side": "right"])
            try await wait(rail, "document.querySelector('[data-visually-tucked=true]') !== null")
            try await wait(rail, "Math.abs(new DOMMatrix(getComputedStyle(document.querySelector('.avatar-face')).transform).m41-40)<0.1")
            try await geometryDiagnostic(rail, window: windows[1], label: "normal-motion close retuck")
        }
        // Recheck after subsequent native/web state round trips, not only on
        // receipt of the first open callback, to catch delayed compatibility clicks.
        XCTAssertEqual(opened, ["agent_first", "agent_first"])
         print("CANONICAL_RAIL_EXERCISED: original512 image source; same component; real WK/profile/owner/replica; typed open and visibility selection")
        print("RAIL_CAPTURE_PERMISSION_EXISTING: \(CGPreflightScreenCaptureAccess())")
    }
}
