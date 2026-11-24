import UIKit
import WebKit

/// One tab as the web app describes it (`web/src/lib/native/tabBar.ts` is the only sender; the tab list itself lives in
/// `web/src/lib/navigation.ts`, so this file holds no destinations).
struct NativeTab: Equatable {
    let id: String
    let label: String
    let symbol: String
    let fallbackSymbol: String?
    /// The tab runs an action in the web app (More opens its sheet) instead of becoming the selected tab.
    let isAction: Bool
}

/// An empty tab page. The app has one web view, so each tab's controller is only a place for it to live: the bridge is moved
/// into whichever host is selected (`CatchTabBarController.embedBridge`). Being a real child of the tab bar controller is what
/// gives the web view a safe area that already includes the floating bar, so `env(safe-area-inset-bottom)` clears it.
final class TabHostViewController: UIViewController {
    override func loadView() {
        view = UIView()
        view.backgroundColor = CatchTabBarController.canvasColor
    }

    override var childForStatusBarStyle: UIViewController? { children.first }
    override var childForStatusBarHidden: UIViewController? { children.first }
}

/// The root of the iOS app (session 38): a standard `UITabBarController`, so the bottom navigation is the system tab bar —
/// Liquid Glass on iOS 26, the classic translucent bar before it — while every page stays the React app in one web view.
/// React Router remains the source of truth for where the person is; this controller shows that state and reports taps.
final class CatchTabBarController: UITabBarController, UITabBarControllerDelegate {
    /// `capacitor.config.json`'s `backgroundColor` (tokens.css `--bg`, dark): what shows for a frame if the web view is ever smaller
    /// than its host, and the colour iOS 26's scroll-edge effect under the bar fades towards.
    static let canvasColor = UIColor(red: 0x0B / 255, green: 0x11 / 255, blue: 0x20 / 255, alpha: 1)
    /// tokens.css `--bg` in the light theme.
    static let lightCanvasColor = UIColor(red: 0xF4 / 255, green: 0xF6 / 255, blue: 0xFB / 255, alpha: 1)

    let bridgeController = CatchBridgeViewController()

    /// Called on a person's tap: (tab id, whether it was already the selected tab).
    var onTabSelected: ((String, Bool) -> Void)?

    private var nativeTabs: [NativeTab] = []
    private var hosts: [TabHostViewController] = []
    /// False from the start of every page load until the web app sends its first `configure`, so a tap can never reach a page
    /// that has no listener yet (the bridge drops plugin listeners on each navigation).
    private(set) var isConfigured = false
    private var loadingObservation: NSKeyValueObservation?
    private var keyboardObservers: [NSObjectProtocol] = []
    /// What the web app asked for (signed in, phone layout, no dialog open).
    private var wantsVisible = false
    /// The keyboard covers the bar anyway; hiding it also takes its inset out of the web view's safe area, so a field sits right
    /// above the keyboard instead of a bar's height higher.
    private var keyboardVisible = false

    override func viewDidLoad() {
        super.viewDidLoad()
        delegate = self
        view.backgroundColor = Self.canvasColor

        let first = TabHostViewController()
        hosts = [first]
        viewControllers = [first]
        embedBridge(in: first)

        if #available(iOS 26.0, *) {
            // The tabs are the app's primary navigation and the pages are short dashboards; Health and Settings keep theirs.
            tabBarMinimizeBehavior = .never
        } else {
            // Before iOS 26: the standard translucent material at every scroll position. A web view gives UIKit no reliable
            // scroll-edge signal, and a bar that turns transparent over a page would look broken.
            let appearance = UITabBarAppearance()
            appearance.configureWithDefaultBackground()
            tabBar.standardAppearance = appearance
            tabBar.scrollEdgeAppearance = appearance
        }
        tabBar.tintColor = UIColor { traits in
            // web/src/styles/tokens.css --accent (dark) and its light-theme value.
            traits.userInterfaceStyle == .dark
                ? UIColor(red: 0x8C / 255, green: 0x9C / 255, blue: 0xFF / 255, alpha: 1)
                : UIColor(red: 0x4D / 255, green: 0x58 / 255, blue: 0xD0 / 255, alpha: 1)
        }
        updateBarVisibility(animated: false)

        let center = NotificationCenter.default
        keyboardObservers = [
            center.addObserver(forName: UIResponder.keyboardWillShowNotification, object: nil, queue: .main) { [weak self] _ in
                self?.keyboardVisible = true
                self?.updateBarVisibility(animated: false)
            },
            center.addObserver(forName: UIResponder.keyboardWillHideNotification, object: nil, queue: .main) { [weak self] _ in
                self?.keyboardVisible = false
                self?.updateBarVisibility(animated: true)
            }
        ]

        loadingObservation = bridgeController.webView?.observe(\.isLoading, options: [.new]) { [weak self] _, change in
            guard change.newValue == true else { return }
            DispatchQueue.main.async { self?.pageWillLoad() }
        }
    }

    deinit {
        loadingObservation?.invalidate()
        keyboardObservers.forEach(NotificationCenter.default.removeObserver)
    }

    // MARK: - State from the web app

    /// The full state, sent by the web app whenever its shell mounts (cold start, after a reload, after sign-in).
    func configure(tabs newTabs: [NativeTab], selected: String?, visible: Bool, theme: String?) {
        if newTabs != nativeTabs {
            nativeTabs = newTabs
            while hosts.count < newTabs.count { hosts.append(TabHostViewController()) }
            for (index, tab) in newTabs.enumerated() {
                let item = UITabBarItem(title: tab.label, image: Self.symbol(tab), tag: index)
                item.accessibilityIdentifier = "tab-\(tab.id)"
                hosts[index].tabBarItem = item
            }
            let current = bridgeController.parent as? TabHostViewController
            let used = Array(hosts.prefix(newTabs.count))
            // Keep the web view's current host in the list while it is swapped, so it never leaves the window.
            if let current, !used.contains(current), let target = used.first {
                embedBridge(in: target)
            }
            setViewControllers(used, animated: false)
        }
        isConfigured = true
        apply(selected: selected, visible: visible, theme: theme)
    }

    /// A partial update; nil leaves that part as it is.
    func apply(selected: String?, visible: Bool?, theme: String?) {
        if let theme {
            tabBar.overrideUserInterfaceStyle = theme == "light" ? .light : theme == "dark" ? .dark : .unspecified
            // The bar's edge effect blends into the web view's own background, which Capacitor sets once to the dark --bg; follow
            // the page's theme so the light theme doesn't get a dark band behind the bar. Only the bar is overridden — never this
            // controller, whose trait would reach the web view's prefers-color-scheme and fight the app's own theme logic.
            let canvas = theme == "light" ? Self.lightCanvasColor : Self.canvasColor
            for v in [bridgeController.webView, bridgeController.webView?.scrollView] { v?.backgroundColor = canvas }
            hosts.forEach { $0.view.backgroundColor = canvas }
        }
        // An action tab can still be shown as selected: More is the current tab on every page it lists.
        if let selected, let index = nativeTabs.firstIndex(where: { $0.id == selected }) {
            select(index)
        }
        if let visible {
            wantsVisible = visible
            updateBarVisibility(animated: true)
        }
    }

    // MARK: - Selection

    private func select(_ index: Int) {
        guard let controllers = viewControllers, index < controllers.count,
              let host = controllers[index] as? TabHostViewController else { return }
        embedBridge(in: host)
        if selectedIndex != index { selectedIndex = index }
        setNeedsStatusBarAppearanceUpdate()
    }

    /// Moves the one bridge controller (and its web view) into `host`. Frame layout, not Auto Layout: the Keyboard and
    /// StatusBar plugins set the web view's frame themselves, and constraints would undo that on the next layout pass.
    private func embedBridge(in host: TabHostViewController) {
        guard bridgeController.parent !== host else { return }
        if bridgeController.parent != nil {
            bridgeController.willMove(toParent: nil)
            bridgeController.view.removeFromSuperview()
            bridgeController.removeFromParent()
        }
        host.addChild(bridgeController)
        bridgeController.view.frame = host.view.bounds
        bridgeController.view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        host.view.addSubview(bridgeController.view)
        bridgeController.didMove(toParent: host)
    }

    func tabBarController(_ tabBarController: UITabBarController, shouldSelect viewController: UIViewController) -> Bool {
        guard isConfigured, let index = viewControllers?.firstIndex(of: viewController), index < nativeTabs.count else { return false }
        let tab = nativeTabs[index]
        let reselected = index == selectedIndex
        if tab.isAction {
            onTabSelected?(tab.id, reselected)
            return false
        }
        // Select at once (native feedback on touch), then tell the web app, which navigates and echoes the same tab back —
        // or corrects it, if the route it lands on belongs to another tab.
        if let host = viewController as? TabHostViewController { embedBridge(in: host) }
        onTabSelected?(tab.id, reselected)
        return true
    }

    // MARK: - Visibility

    private func updateBarVisibility(animated: Bool) {
        let hidden = !(wantsVisible && isConfigured && !keyboardVisible)
        if #available(iOS 18.0, *) {
            guard isTabBarHidden != hidden else { return }
            setTabBarHidden(hidden, animated: animated && !UIAccessibility.isReduceMotionEnabled && view.window != nil)
        } else {
            tabBar.isHidden = hidden
        }
    }

    private func pageWillLoad() {
        isConfigured = false
        wantsVisible = false
        updateBarVisibility(animated: false)
    }

    // MARK: - Forwarded to the bridge

    override var childForStatusBarStyle: UIViewController? { bridgeController }
    override var childForStatusBarHidden: UIViewController? { bridgeController }
    override var supportedInterfaceOrientations: UIInterfaceOrientationMask { bridgeController.supportedInterfaceOrientations }

    // MARK: - Symbols

    private static func symbol(_ tab: NativeTab) -> UIImage? {
        if let image = UIImage(systemName: tab.symbol) { return image }
        if let fallback = tab.fallbackSymbol, let image = UIImage(systemName: fallback) { return image }
        return UIImage(systemName: "circle")
    }
}
