import XCTest

/// Session 38: the native tab bar drives the React app and follows it. Runs against the fixtures-only native bundle (no backend):
///   cd web && CATCH_NATIVE_ENV=development node scripts/native-config.mjs \
///     && VITE_CATCH_MOCK=1 npx vite build --mode native-development && npx cap sync ios
/// then `xcodebuild test -scheme App …` (docs/mobile/README.md "Testing").
final class NativeTabBarUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launch()
        XCTAssertTrue(tab("Today").waitForExistence(timeout: 20), "the native tab bar never appeared")
        XCTAssertTrue(webText("Today").waitForExistence(timeout: 10))
    }

    // MARK: - Helpers

    private func tab(_ label: String) -> XCUIElement { app.tabBars.buttons[label] }

    private func webText(_ label: String) -> XCUIElement {
        app.webViews.staticTexts.matching(NSPredicate(format: "label == %@", label)).firstMatch
    }

    /// A link by the start of its accessible name (a tile's name is its title followed by its one-line description).
    private func webLink(_ prefix: String) -> XCUIElement {
        app.webViews.links.matching(NSPredicate(format: "label BEGINSWITH %@", prefix)).firstMatch
    }

    private func waitFor(_ element: XCUIElement, _ predicate: String, timeout: TimeInterval = 5,
                         file: StaticString = #filePath, line: UInt = #line) {
        let expectation = XCTNSPredicateExpectation(predicate: NSPredicate(format: predicate), object: element)
        XCTAssertEqual(XCTWaiter().wait(for: [expectation], timeout: timeout), .completed,
                       "\(element) never matched \(predicate)", file: file, line: line)
    }

    private func assertSelected(_ label: String, file: StaticString = #filePath, line: UInt = #line) {
        waitFor(tab(label), "isSelected == true", file: file, line: line)
    }

    // MARK: - Native → React

    func testEachTabNavigatesTheWebApp() {
        assertSelected("Today")
        tab("Plan").tap()
        XCTAssertTrue(webText("Calendar").waitForExistence(timeout: 5))
        assertSelected("Plan")
        tab("Train").tap()
        XCTAssertTrue(webText("Log, review and plan the work.").waitForExistence(timeout: 5))
        assertSelected("Train")
        tab("Coach").tap()
        XCTAssertTrue(app.webViews.textViews.firstMatch.waitForExistence(timeout: 5))
        assertSelected("Coach")
        tab("Today").tap()
        XCTAssertTrue(webText("Today").waitForExistence(timeout: 5))
        XCTAssertFalse(app.webViews.textViews.firstMatch.exists)
        assertSelected("Today")
    }

    func testExactlyOneNavigationSurface() {
        // The web tab bar's More button (aria-label "More") must not be rendered under the native bar.
        XCTAssertFalse(app.webViews.buttons["More"].exists)
        XCTAssertEqual(app.tabBars.count, 1)
        XCTAssertEqual(app.tabBars.buttons.count, 5)
    }

    func testMoreOpensTheSheetAndTheBarStepsAside() {
        tab("More").tap()
        XCTAssertTrue(webText("Everything else in Catch.").waitForExistence(timeout: 5))
        // A sheet is presented over the tab bar, as on iOS.
        waitFor(tab("Today"), "hittable == false")
        webLink("Body ").tap()
        XCTAssertTrue(webText("Weight, composition and power for your size — one resolved reading per day.").waitForExistence(timeout: 5))
        waitFor(tab("Today"), "hittable == true")
        assertSelected("More")
    }

    func testReselectingATabFromDeeperInItsSectionReturnsToItsRoot() {
        tab("Train").tap()
        XCTAssertTrue(webText("Log, review and plan the work.").waitForExistence(timeout: 5))
        webLink("Workouts ").tap()
        waitFor(webText("Log, review and plan the work."), "exists == false")
        assertSelected("Train")
        tab("Train").tap()
        XCTAssertTrue(webText("Log, review and plan the work.").waitForExistence(timeout: 5))
    }

    // MARK: - React → native

    func testAnInAppLinkMovesTheSelection() {
        app.webViews.links["Settings"].firstMatch.tap()
        assertSelected("More")
        app.webViews.links["Catch — Today"].firstMatch.tap()
        assertSelected("Today")
    }

    func testDeepLinkSelectsItsTab() throws {
        guard #available(iOS 16.4, *) else { throw XCTSkip("XCUIApplication.open(_:) needs iOS 16.4") }
        // The development build's URL scheme (CATCH_ID_SUFFIX=.dev; Info.plist CFBundleURLSchemes).
        app.open(URL(string: "com.openoted.catch.dev://calendar")!)
        XCTAssertTrue(webText("Calendar").waitForExistence(timeout: 10))
        assertSelected("Plan")
    }

    func testStateSurvivesBackgrounding() {
        tab("Plan").tap()
        assertSelected("Plan")
        XCUIDevice.shared.press(.home)
        XCTAssertTrue(app.wait(for: .runningBackground, timeout: 5) || app.wait(for: .runningBackgroundSuspended, timeout: 5))
        app.activate()
        XCTAssertTrue(app.wait(for: .runningForeground, timeout: 5))
        waitFor(tab("Plan"), "hittable == true")
        assertSelected("Plan")
        XCTAssertTrue(webText("Calendar").exists)
    }

    // MARK: - Safe area and keyboard

    /// Content scrolls under the glass, and the end of a page comes to rest above the bar.
    func testTheEndOfAPageRestsAboveTheBar() {
        tab("Train").tap()
        XCTAssertTrue(webText("Log, review and plan the work.").waitForExistence(timeout: 5))
        let web = app.webViews.firstMatch
        for _ in 0..<8 { web.swipeUp(velocity: .fast) }
        sleep(1)
        let last = web.links.allElementsBoundByIndex.filter { $0.frame.height > 0 }.max { $0.frame.maxY < $1.frame.maxY }
        let barTop = app.tabBars.firstMatch.buttons.firstMatch.frame.minY
        XCTAssertNotNil(last)
        XCTAssertLessThanOrEqual(last!.frame.maxY, barTop, "the last row stays under the tab bar")
        XCTAssertTrue(last!.isHittable)
    }

    func testRotationKeepsTheBarAndTheSelection() {
        tab("Plan").tap()
        assertSelected("Plan")
        XCUIDevice.shared.orientation = .landscapeLeft
        defer { XCUIDevice.shared.orientation = .portrait }
        waitFor(tab("Plan"), "hittable == true")
        assertSelected("Plan")
        tab("Coach").tap()
        assertSelected("Coach")
        XCTAssertTrue(app.webViews.textViews.firstMatch.waitForExistence(timeout: 5))
    }

    /// The bar's footprint reaches the page only through the safe area (--shell-bottom is 0 in the app): Coach's composer sits just
    /// above the bar — not behind it, and not a second bar-height higher.
    func testCoachComposerSitsJustAboveTheBarAndTheKeyboard() throws {
        tab("Coach").tap()
        let composer = app.webViews.textViews.firstMatch
        XCTAssertTrue(composer.waitForExistence(timeout: 5))
        let barTop = app.tabBars.firstMatch.buttons.firstMatch.frame.minY
        let gap = barTop - composer.frame.maxY
        XCTAssertGreaterThanOrEqual(gap, 0, "composer is under the tab bar")
        XCTAssertLessThan(gap, 70, "composer is padded for the tab bar twice")

        composer.tap()
        let keyboard = app.keyboards.firstMatch
        guard keyboard.waitForExistence(timeout: 5), keyboard.frame.minY < app.frame.maxY else {
            throw XCTSkip("No software keyboard (the simulator has its hardware keyboard connected)")
        }
        sleep(1) // the Keyboard plugin resizes the web view after the keyboard animation
        XCTAssertFalse(tab("Coach").isHittable, "the bar stays up under the keyboard")
        // The Keyboard plugin shrinks the web view to the keyboard's top edge (its accessibility frame excludes the suggestions row).
        let webBottom = app.webViews.firstMatch.frame.maxY
        XCTAssertLessThanOrEqual(webBottom, keyboard.frame.minY + 1)
        let keyboardGap = webBottom - composer.frame.maxY
        XCTAssertGreaterThanOrEqual(keyboardGap, 0, "composer is under the keyboard")
        XCTAssertLessThan(keyboardGap, 70, "the tab bar's inset was kept while the keyboard covers the bar")
    }
}
