import AppKit
import WebKit

struct UsageSnap: Decodable {
    struct Provider: Decodable {
        struct Window: Decodable {
            let used: Int
            let approx: Bool?
        }
        let id: String
        let name: String
        let ok: Bool
        let windows: [Window]
    }
    let providers: [Provider]
}

private let statusAutosaveName = "Namum"

// 0 is the slot next to Control Center. Larger numbers sit further left and
// disappear first when the menu bar runs out of room.
private func pinStatusItemToFront() {
    let defaults = UserDefaults.standard
    defaults.set(0, forKey: "NSStatusItem Preferred Position \(statusAutosaveName)")
    defaults.set(true, forKey: "NSStatusItem Visible \(statusAutosaveName)")
}

private func raiseStatusItem(_ item: NSStatusItem) {
    let sel = NSSelectorFromString("_setPriority:")
    guard item.responds(to: sel), let imp = item.method(for: sel) else { return }
    typealias SetPriority = @convention(c) (AnyObject, Selector, Int) -> Void
    unsafeBitCast(imp, to: SetPriority.self)(item, sel, Int.max)
}

private let providerOrder = ["chatgpt", "claude", "grok", "gemini"]

private func providerRank(_ id: String) -> Int {
    providerOrder.firstIndex(of: id) ?? 99
}

private func statusImage(_ columns: [(id: String, percent: String)]) -> NSImage {
    let font = NSFont.monospacedDigitSystemFont(ofSize: 8, weight: .semibold)
    let textAttr: [NSAttributedString.Key: Any] = [
        .font: font,
        .foregroundColor: NSColor.black
    ]
    let logo: CGFloat = 11
    let gap: CGFloat = 5
    let textHeight: CGFloat = 9
    let columnWidth: CGFloat = 22
    let width = CGFloat(columns.count) * columnWidth + CGFloat(max(0, columns.count - 1)) * gap
    let height = logo + 2 + textHeight
    let image = NSImage(size: NSSize(width: width, height: height))
    image.lockFocus()
    for (index, column) in columns.enumerated() {
        let x = CGFloat(index) * (columnWidth + gap)
        drawLogo(column.id, in: NSRect(x: x + (columnWidth - logo) / 2, y: textHeight + 2, width: logo, height: logo))
        let text = column.percent as NSString
        let size = text.size(withAttributes: textAttr)
        text.draw(
            in: NSRect(x: x + (columnWidth - size.width) / 2, y: (textHeight - size.height) / 2, width: size.width, height: size.height),
            withAttributes: textAttr
        )
    }
    image.unlockFocus()
    image.isTemplate = true
    return image
}

private func logoImage(_ id: String) -> NSImage? {
    let bundled = Bundle.main.bundleURL.appendingPathComponent("Contents/Resources/logos/\(id).png")
    let beside = Bundle.main.bundleURL.deletingLastPathComponent().appendingPathComponent("assets/logos/\(id).png")
    let url = FileManager.default.fileExists(atPath: bundled.path) ? bundled : beside
    return NSImage(contentsOf: url)
}

private func drawLogo(_ id: String, in rect: NSRect) {
    guard let image = logoImage(id), image.size.width > 0, image.size.height > 0 else { return }
    let scale = min(rect.width / image.size.width, rect.height / image.size.height)
    let w = image.size.width * scale
    let h = image.size.height * scale
    let dest = NSRect(x: rect.midX - w / 2, y: rect.midY - h / 2, width: w, height: h)
    image.draw(in: dest, from: NSRect(origin: .zero, size: image.size), operation: .sourceOver, fraction: 1)
}

final class MenuPanel: NSPanel {
    var allowShow = false

    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }

    override func orderFront(_ sender: Any?) {
        guard allowShow else { return }
        level = .popUpMenu
        super.orderFront(sender)
    }

    override func makeKeyAndOrderFront(_ sender: Any?) {
        guard allowShow else { return }
        level = .popUpMenu
        super.makeKeyAndOrderFront(sender)
    }

    override func orderFrontRegardless() {
        guard allowShow else { return }
        level = .popUpMenu
        super.orderFrontRegardless()
    }
}

final class App: NSObject, NSApplicationDelegate, NSWindowDelegate, NSMenuDelegate, WKNavigationDelegate {
    let port = 8737
    var window: NSWindow!
    var web: WKWebView!
    var server: Process?
    var ownsServer = false
    var statusItem: NSStatusItem!
    var refreshTimer: Timer?
    var bootTimer: Timer?
    var bootTries = 0
    var remembered: [String: (text: String, emphasis: Bool)] = [:]
    var monitorsInstalled = false
    var panelSize = NSSize(width: 368, height: 420)

    var pageURL: URL { URL(string: "http://127.0.0.1:\(port)/")! }

    func applicationDidFinishLaunching(_ notification: Notification) {
        makeStatusItem()
        makeWindow()
        if let icon = NSImage(contentsOf: repo().appendingPathComponent("static/icon-512.png")) {
            NSApp.applicationIconImage = icon
        }
        if healthOK() {
            web.load(URLRequest(url: pageURL))
            refreshStatus()
        } else {
            startServer()
            bootTimer = Timer.scheduledTimer(withTimeInterval: 0.15, repeats: true) { [weak self] timer in
                guard let self else { return }
                self.bootTries += 1
                let died = self.server != nil && self.server?.isRunning == false
                if self.healthOK() {
                    timer.invalidate()
                    self.web.load(URLRequest(url: self.pageURL))
                    self.refreshStatus()
                } else if self.bootTries > 40 || died {
                    timer.invalidate()
                    self.alert("남음을 시작하지 못했습니다. /tmp/namum-server.log 를 확인해 주세요.")
                }
            }
        }
        refreshTimer = Timer.scheduledTimer(withTimeInterval: 90, repeats: true) { [weak self] _ in
            self?.refreshStatus()
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    func applicationWillTerminate(_ notification: Notification) {
        guard ownsServer, let server, server.isRunning else { return }
        server.terminate()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag { showWindow() }
        return true
    }

    func makeStatusItem() {
        pinStatusItemToFront()
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.autosaveName = statusAutosaveName
        raiseStatusItem(statusItem)
        guard let button = statusItem.button else { return }
        button.imagePosition = .imageOnly
        button.image = statusImage([("chatgpt", "…"), ("claude", "…"), ("grok", "…"), ("gemini", "…")])
        button.toolTip = "남음"
        button.target = self
        button.action = #selector(statusClicked)
        button.sendAction(on: [.leftMouseUp, .rightMouseUp])
    }

    @objc func statusClicked() {
        let event = NSApp.currentEvent
        let right = event?.type == .rightMouseUp || event?.modifierFlags.contains(.control) == true
        if right {
            hidePanel()
            popMenu()
            return
        }
        toggleWindow()
    }

    func popMenu() {
        let menu = NSMenu()
        menu.delegate = self
        let open = menu.addItem(withTitle: "열기", action: #selector(showWindow), keyEquivalent: "")
        menu.addItem(.separator())
        let quit = menu.addItem(withTitle: "종료", action: #selector(quit), keyEquivalent: "q")
        open.target = self
        quit.target = self
        statusItem.menu = menu
        statusItem.button?.performClick(nil)
    }

    func menuDidClose(_ menu: NSMenu) {
        statusItem.menu = nil
    }

    @objc func quit() {
        NSApp.terminate(nil)
    }

    func toggleWindow() {
        if window.isVisible {
            hidePanel()
            return
        }
        showWindow()
    }

    @objc func showWindow() {
        (window as? MenuPanel)?.allowShow = true
        placePanel()
        window.orderFrontRegardless()
        setStatusHighlight(true)
        installMonitors()
        fitPanel()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self] in
            self?.fitPanel()
        }
    }

    func fitPanel() {
        web.evaluateJavaScript("Math.ceil(document.querySelector('.wrap').getBoundingClientRect().height)") { [weak self] result, _ in
            guard let self, let number = result as? NSNumber else { return }
            let height = min(720, max(220, CGFloat(truncating: number)))
            DispatchQueue.main.async {
                guard abs(height - self.panelSize.height) > 1 else { return }
                self.panelSize.height = height
                if self.window.isVisible { self.placePanel() }
            }
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        fitPanel()
    }

    func hidePanel() {
        guard window.isVisible else { return }
        window.orderOut(nil)
        setStatusHighlight(false)
    }

    func setStatusHighlight(_ on: Bool) {
        guard let button = statusItem.button else { return }
        let sel = NSSelectorFromString("highlight:")
        guard button.responds(to: sel) else { return }
        let imp = button.method(for: sel)
        typealias Highlight = @convention(c) (AnyObject, Selector, Bool) -> Void
        unsafeBitCast(imp, to: Highlight.self)(button, sel, on)
    }

    func placePanel() {
        guard let button = statusItem.button, let host = button.window else { return }
        let anchor = host.convertToScreen(button.convert(button.bounds, to: nil))
        var x = anchor.midX - panelSize.width / 2
        let y = anchor.minY - panelSize.height - 4
        if let screen = host.screen ?? NSScreen.main {
            let visible = screen.visibleFrame
            x = min(max(x, visible.minX + 8), visible.maxX - panelSize.width - 8)
        }
        window.setFrame(NSRect(x: x, y: y, width: panelSize.width, height: panelSize.height), display: true)
        window.level = .popUpMenu
    }

    func installMonitors() {
        guard !monitorsInstalled else { return }
        monitorsInstalled = true
        NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
            DispatchQueue.main.async { self?.hidePanel() }
        }
        NSEvent.addLocalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown, .keyDown]) { [weak self] event in
            guard let self, self.window.isVisible else { return event }
            if event.type == .keyDown {
                if event.keyCode == 53 { self.hidePanel() }
                return event
            }
            if event.window === self.window || event.window === self.statusItem.button?.window {
                return event
            }
            self.hidePanel()
            return event
        }
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        hidePanel()
        return false
    }

    func makeWindow() {
        window = MenuPanel(
            contentRect: NSRect(origin: .zero, size: panelSize),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        window.level = .popUpMenu
        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = true
        window.isMovable = false
        window.hidesOnDeactivate = false
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .transient, .ignoresCycle]
        window.isReleasedWhenClosed = false
        window.isRestorable = false
        window.delegate = self
        window.orderOut(nil)

        let effect = NSVisualEffectView(frame: NSRect(origin: .zero, size: panelSize))
        effect.autoresizingMask = [.width, .height]
        effect.material = .menu
        effect.blendingMode = .behindWindow
        effect.state = .active
        effect.wantsLayer = true
        effect.layer?.cornerRadius = 12
        effect.layer?.masksToBounds = true
        window.contentView = effect

        let config = WKWebViewConfiguration()
        web = WKWebView(frame: effect.bounds, configuration: config)
        web.autoresizingMask = [.width, .height]
        web.navigationDelegate = self
        web.setValue(false, forKey: "drawsBackground")
        web.underPageBackgroundColor = .clear
        effect.addSubview(web)
    }

    func refreshStatus() {
        guard let url = URL(string: "http://127.0.0.1:\(port)/api/usage") else { return }
        URLSession.shared.dataTask(with: url) { data, _, _ in
            guard let data, let snap = try? JSONDecoder().decode(UsageSnap.self, from: data) else { return }
            DispatchQueue.main.async { self.apply(snap) }
        }.resume()
    }

    func apply(_ snap: UsageSnap) {
        let sorted = snap.providers.sorted { providerRank($0.id) < providerRank($1.id) }
        var parts: [(text: String, emphasis: Bool)] = []
        for provider in sorted {
            if provider.ok, let fullest = provider.windows.max(by: { $0.used < $1.used }) {
                let text = fullest.approx == true && fullest.used == 0 ? "<1" : String(fullest.used)
                remembered[provider.id] = (text, fullest.used >= 80)
            } else if !provider.ok {
                remembered[provider.id] = ("–", false)
            }
            parts.append(remembered[provider.id] ?? ("…", false))
        }
        guard parts.contains(where: { $0.text != "…" }) else { return }
        let columns = zip(sorted, parts).map { provider, part in
            (id: provider.id, percent: part.text == "…" || part.text == "–" ? part.text : part.text + "%")
        }
        statusItem.button?.image = statusImage(columns)
        let named = zip(sorted, parts).map { provider, part in
            if part.text == "…" || part.text == "–" { return provider.name }
            return "\(provider.name) \(part.text)% used"
        }
        statusItem.button?.toolTip = named.joined(separator: "  ·  ")
        raiseStatusItem(statusItem)
    }

    func repo() -> URL {
        Bundle.main.bundleURL.deletingLastPathComponent()
    }

    func healthOK() -> Bool {
        guard let url = URL(string: "http://127.0.0.1:\(port)/api/health") else { return false }
        var request = URLRequest(url: url, timeoutInterval: 0.4)
        request.httpMethod = "GET"
        let sem = DispatchSemaphore(value: 0)
        var ok = false
        URLSession.shared.dataTask(with: request) { data, response, _ in
            if let http = response as? HTTPURLResponse, http.statusCode == 200,
               let data, let text = String(data: data, encoding: .utf8), text.contains("namum") {
                ok = true
            }
            sem.signal()
        }.resume()
        _ = sem.wait(timeout: .now() + 0.6)
        return ok
    }

    func startServer() {
        let script = repo().appendingPathComponent("server.py")
        guard FileManager.default.fileExists(atPath: script.path) else {
            alert("server.py 가 앱 옆에 없습니다.")
            return
        }
        let logURL = URL(fileURLWithPath: "/tmp/namum-server.log")
        FileManager.default.createFile(atPath: logURL.path, contents: nil)
        let handle = try? FileHandle(forWritingTo: logURL)
        handle?.seekToEndOfFile()
        let marker = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Namum/lan")
        var arguments = [script.path]
        if ProcessInfo.processInfo.environment["NAMUM_LAN"] == "1"
            || FileManager.default.fileExists(atPath: marker.path) {
            arguments.append("--lan")
        }
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        proc.arguments = arguments
        proc.currentDirectoryURL = repo()
        var env = ProcessInfo.processInfo.environment
        env["PORT"] = String(port)
        proc.environment = env
        proc.standardOutput = handle
        proc.standardError = handle
        do {
            try proc.run()
            server = proc
            ownsServer = true
        } catch {
            alert("파이썬을 실행하지 못했습니다.")
        }
    }

    func alert(_ text: String) {
        let alert = NSAlert()
        alert.messageText = "남음"
        alert.informativeText = text
        alert.runModal()
    }
}

UserDefaults.standard.set(true, forKey: "ApplePersistenceIgnoreState")
let app = NSApplication.shared
let delegate = App()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
