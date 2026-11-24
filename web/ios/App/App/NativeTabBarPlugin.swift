import UIKit
import Capacitor

/// The bridge between the native tab bar and the web app (session 38). The web side is `web/src/lib/native/tabBar.ts`;
/// nothing else in the web app talks to this plugin.
///
/// Web → native: `configure` (the full state, sent each time the app shell mounts) and `setState` (only what changed).
/// Native → web: `tabSelected` {id, reselected} on a person's tap, and `accessibility` {reduceTransparency} when that
/// system setting changes. Programmatic selection never raises `tabSelected`, so the two directions cannot loop.
@objc(NativeTabBarPlugin)
public class NativeTabBarPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "NativeTabBarPlugin"
    public let jsName = "NativeTabBar"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "configure", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setState", returnType: CAPPluginReturnPromise)
    ]

    private var accessibilityObserver: NSObjectProtocol?

    /// Looked up on each call rather than kept: the bridge controller's ancestor is the root tab bar controller.
    private var controller: CatchTabBarController? {
        bridge?.viewController?.tabBarController as? CatchTabBarController
    }

    override public func load() {
        accessibilityObserver = NotificationCenter.default.addObserver(
            forName: UIAccessibility.reduceTransparencyStatusDidChangeNotification, object: nil, queue: .main
        ) { [weak self] _ in
            self?.notifyListeners("accessibility", data: Self.accessibilityState())
        }
    }

    deinit {
        if let accessibilityObserver { NotificationCenter.default.removeObserver(accessibilityObserver) }
    }

    @objc func configure(_ call: CAPPluginCall) {
        let tabs: [NativeTab] = (call.getArray("tabs", JSObject.self) ?? []).compactMap { raw in
            guard let id = raw["id"] as? String, let label = raw["label"] as? String, let symbol = raw["symbol"] as? String else {
                return nil
            }
            return NativeTab(id: id, label: label, symbol: symbol, fallbackSymbol: raw["fallbackSymbol"] as? String,
                             isAction: raw["action"] as? Bool ?? false)
        }
        guard !tabs.isEmpty else {
            call.reject("configure needs at least one tab")
            return
        }
        let selected = call.getString("selected")
        let visible = call.getBool("visible") ?? false
        let theme = call.getString("theme")
        DispatchQueue.main.async { [weak self] in
            guard let self, let controller = self.controller else {
                call.reject("The native tab bar is not available")
                return
            }
            controller.onTabSelected = { [weak self] id, reselected in
                self?.notifyListeners("tabSelected", data: ["id": id, "reselected": reselected])
            }
            controller.configure(tabs: tabs, selected: selected, visible: visible, theme: theme)
            call.resolve(Self.accessibilityState())
        }
    }

    @objc func setState(_ call: CAPPluginCall) {
        let selected = call.getString("selected")
        let visible = call.getBool("visible")
        let theme = call.getString("theme")
        DispatchQueue.main.async { [weak self] in
            guard let controller = self?.controller, controller.isConfigured else {
                // Before `configure` (or during a reload) there is nothing to update; the next `configure` carries it all.
                call.resolve()
                return
            }
            controller.apply(selected: selected, visible: visible, theme: theme)
            call.resolve()
        }
    }

    private static func accessibilityState() -> [String: Any] {
        ["reduceTransparency": UIAccessibility.isReduceTransparencyEnabled]
    }
}
