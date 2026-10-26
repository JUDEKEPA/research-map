import Cocoa
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, WKScriptMessageHandler, WKNavigationDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var process: Process?
    var ready: URL!
    var timer: Timer?
    var launcherURL: URL?
    var attempts = 0
    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let appItem = NSMenuItem(); menu.addItem(appItem)
        let appMenu = NSMenu(); appItem.submenu = appMenu
        appMenu.addItem(withTitle: "Quit Research Map Community", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let editItem = NSMenuItem(); menu.addItem(editItem); let edit = NSMenu(title: "Edit"); editItem.submenu = edit
        for (title, action, key) in [("Copy", "copy:", "c"), ("Paste", "paste:", "v"), ("Cut", "cut:", "x"), ("Select All", "selectAll:", "a")] { edit.addItem(withTitle:title, action:Selector(action), keyEquivalent:key) }
        NSApp.mainMenu = menu
        let config = WKWebViewConfiguration(); config.userContentController.add(self, name:"chooseProject")
        web = WKWebView(frame:.zero, configuration:config); web.navigationDelegate = self
        web.setValue(false, forKey:"drawsBackground")
        window = NSWindow(contentRect:NSRect(x:0,y:0,width:1280,height:820),styleMask:[.titled,.closable,.miniaturizable,.resizable],backing:.buffered,defer:false)
        window.title = "Research Map Community"; window.backgroundColor = NSColor(calibratedWhite:0.118,alpha:1); window.contentView = web; window.center(); window.makeKeyAndOrderFront(nil)
        window.setFrameAutosaveName("ResearchMapCommunityMainWindow"); NSApp.activate(ignoringOtherApps:true)
        startBackend()
    }
    func startBackend() {
        guard let resources = Bundle.main.resourceURL else { return }
        let runtime = resources.appendingPathComponent("app")
        let pythonFile = resources.appendingPathComponent("python-path.txt")
        let configured = (try? String(contentsOf:pythonFile).trimmingCharacters(in:.whitespacesAndNewlines)) ?? ""
        let candidates = [configured, "/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]
        guard let python = candidates.first(where:{ !$0.isEmpty && FileManager.default.isExecutableFile(atPath:$0) }) else { fail("Python 3 is required. Install Python, then reopen Research Map Community."); return }
        ready = FileManager.default.temporaryDirectory.appendingPathComponent("research-map-\(UUID().uuidString).json")
        let child = Process(); child.executableURL = URL(fileURLWithPath:python)
        child.arguments = [runtime.appendingPathComponent("launcher.py").path,"--port","0","--ready-file",ready.path]
        let env = ProcessInfo.processInfo.environment
        var clean = env; clean.removeValue(forKey:"CODEX_THREAD_ID");clean.removeValue(forKey:"CODEX_INTERNAL_ORIGINATOR_OVERRIDE");child.environment = clean
        let log = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/Research Map Community")
        try? FileManager.default.createDirectory(at:log,withIntermediateDirectories:true)
        let file = log.appendingPathComponent("launcher.log"); FileManager.default.createFile(atPath:file.path,contents:nil)
        child.standardOutput = try? FileHandle(forWritingTo:file); child.standardError = child.standardOutput
        do { try child.run(); process = child } catch { fail("Could not start the local app: \(error.localizedDescription)");return }
        timer = Timer.scheduledTimer(withTimeInterval:0.15,repeats:true) { [weak self] _ in
            guard let self = self else { return }; self.attempts += 1
            if let data = try? Data(contentsOf:self.ready), let json = try? JSONSerialization.jsonObject(with:data) as? [String:String], let address = json["url"], let url = URL(string:address) {
                self.timer?.invalidate();self.launcherURL = url;self.web.load(URLRequest(url:url));try? FileManager.default.removeItem(at:self.ready)
            } else if !child.isRunning || self.attempts > 200 { self.timer?.invalidate();self.fail("The local project opener could not start. See ~/Library/Logs/Research Map Community/launcher.log.") }
        }
    }
    func fail(_ message:String) { let alert=NSAlert();alert.messageText="Research Map Community";alert.informativeText=message;alert.runModal() }
    func userContentController(_ userContentController:WKUserContentController,didReceive message:WKScriptMessage) {
        guard message.name=="chooseProject",message.frameInfo.isMainFrame,message.frameInfo.securityOrigin.host=="127.0.0.1",message.frameInfo.securityOrigin.port==launcherURL?.port else{return}
        let picker=NSOpenPanel();picker.canChooseDirectories=true;picker.canChooseFiles=false;picker.allowsMultipleSelection=false;picker.prompt="Open project";picker.message="Choose the folder containing your research. App metadata will be stored inside .research-map."
        picker.beginSheetModal(for:window) { [weak self] result in
            guard result == .OK, let path=picker.url?.path,let data=try? JSONSerialization.data(withJSONObject:[path]),let encoded=String(data:data,encoding:.utf8) else{return}
            self?.web.evaluateJavaScript("window.researchFolderSelected(\(encoded)[0])",completionHandler:nil)
        }
    }
    func webView(_ webView:WKWebView,decidePolicyFor navigationAction:WKNavigationAction,decisionHandler:@escaping(WKNavigationActionPolicy)->Void) {
        guard let url=navigationAction.request.url else{decisionHandler(.cancel);return}
        if url.host=="127.0.0.1" && url.scheme=="http" { decisionHandler(.allow) } else { decisionHandler(.cancel) }
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender:NSApplication)->Bool{return true}
    func applicationWillTerminate(_ notification:Notification){ timer?.invalidate();if let child=process,child.isRunning{child.interrupt();child.waitUntilExit()} }
}
let application=NSApplication.shared
let delegate=AppDelegate()
application.delegate=delegate
application.setActivationPolicy(.regular)
application.run()
