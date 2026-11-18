import { expect, test, type Locator, type Page } from "@playwright/test";

// Clubs, team training and challenges at the iPhone 13 profile (390px), real touch taps, under both mobile projects. Everything is ?mock=1; the mock is in
// memory per page load, so each flow stays inside the SPA (links and taps, never page.goto between steps). The mock fabricates the server's `capabilities`:
//   ?role=athlete|coach|admin|owner  your role in River Rowing Club (default admin)   &junior=1&jrole=athlete|coach|owner  adds Junior Squad   &noprofile=1

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
});

async function noHorizontalOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
}

async function aboveNav(page: Page, target: Locator) {
  await expect
    .poll(async () => {
      await target.scrollIntoViewIfNeeded();
      return target.evaluate((el) => {
        const r = el.getBoundingClientRect();
        const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return !!top && (el === top || el.contains(top));
      });
    })
    .toBe(true);
}

async function openClub(page: Page, name: string) {
  await page.getByTestId("club-link").filter({ hasText: name }).tap();
  await expect(page.getByTestId("club-page")).toBeVisible();
}

async function tab(page: Page, key: string) {
  const t = page.getByTestId(`club-tab-${key}`);
  await t.scrollIntoViewIfNeeded();
  await t.tap();
  await expect(t).toHaveAttribute("aria-selected", "true");
}

// ---------------------------------------------------------------- the hub

test("your clubs show who can see inside, who they're for and your role, and discovery lists public clubs with a count and no members", async ({ page }) => {
  await page.goto("/clubs?mock=1&junior=1");
  const mine = page.getByTestId("clubs-mine");
  await expect(mine).toContainText("River Rowing Club");
  await expect(mine.getByTestId("privacy-badge").first()).toHaveAttribute("data-visibility", "club"); // a private club is "club-only", never mistaken for public
  await expect(mine.getByTestId("junior-badge")).toContainText("Junior club · under 19");
  await expect(mine.getByTestId("role-badge").first()).toBeVisible();
  const discover = page.getByTestId("clubs-discover");
  await expect(discover).toContainText("Open Water Club");
  await expect(discover).toContainText("128 members");
  await expect(discover).not.toContainText("Junior Squad"); // a junior club is never listed
  await expect(discover).not.toContainText("River Rowing Club"); // nor a private one
  await noHorizontalOverflow(page);
});

test("clubs need a profile first: a handle and an age group, and under 16 needs a guardian's agreement", async ({ page }) => {
  await page.goto("/clubs?mock=1&noprofile=1");
  await expect(page.getByTestId("clubs-start")).toHaveCount(0); // nothing to start or join before a profile
  await page.getByTestId("clubs-profile-setup").tap();
  const sheet = page.getByTestId("profile-sheet");
  await expect(sheet).toBeVisible();
  await expect(sheet).toContainText("never your real name or email");
  await sheet.getByTestId("profile-handle").fill("Row Fan");
  await sheet.getByTestId("profile-band").selectOption("U15");
  await sheet.getByTestId("profile-attest").check();
  await aboveNav(page, sheet.getByTestId("profile-save"));
  await sheet.getByTestId("profile-save").tap();
  await expect(sheet.getByRole("alert")).toContainText("parent or guardian"); // the server's own wording
  await sheet.getByTestId("profile-guardian").check();
  await sheet.getByTestId("profile-save").tap();
  await expect(sheet).toBeHidden();
  await expect(page.getByTestId("profile-handle-shown")).toHaveText("Row Fan");
  await noHorizontalOverflow(page);
});

test("a public club shows what it is and how to join, but its insides stay members-only", async ({ page }) => {
  await page.goto("/clubs?mock=1");
  await page.getByTestId("discover-row").filter({ hasText: "Open Water Club" }).tap();
  const view = page.getByTestId("club-public-view");
  await expect(view).toContainText("Members-only inside");
  await expect(page.locator('[role="tablist"]')).toHaveCount(0); // no members, calendar or board for a visitor
  await expect(view).toContainText("Be kind."); // but the rules are shown before joining
  await expect(page.getByTestId("join-go")).toBeDisabled(); // until the rules are accepted
  await page.getByTestId("join-accept-rules").check();
  await page.getByTestId("join-go").tap();
  await expect(page.getByTestId("club-header")).toContainText("Open Water Club");
  await expect(page.locator('[role="tablist"]')).toBeVisible(); // now a member
  await noHorizontalOverflow(page);
});

// ---------------------------------------------------------------- an adult club

test("the club tab bar scrolls inside itself and never widens the page", async ({ page }) => {
  await page.goto("/clubs?mock=1");
  await openClub(page, "River Rowing Club");
  for (const key of ["news", "calendar", "challenges", "board", "members", "manage", "overview"]) {
    await tab(page, key);
    await noHorizontalOverflow(page);
  }
});

test("rules and what you share are labelled club-only, and no health value appears anywhere in a club", async ({ page }) => {
  await page.goto("/clubs?mock=1");
  await openClub(page, "River Rowing Club");
  const rules = page.getByTestId("club-rules-text");
  await expect(rules).toContainText("Look out for each other");
  await expect(page.getByTestId("club-overview").getByTestId("privacy-badge").first()).toHaveAttribute("data-visibility", "club");
  await expect(page.getByTestId("club-overview")).toContainText("never shared with a club");
  await tab(page, "members");
  const text = (await page.getByTestId("club-members").innerText()).toLowerCase();
  for (const word of ["hrv", "sleep", "recovery", "weight", "calorie", "heart rate"]) expect(text).not.toContain(word);
  await noHorizontalOverflow(page);
});

test("an admin removes a member only with a written reason, and a role menu offers what the role may do", async ({ page }) => {
  await page.goto("/clubs?mock=1&role=admin");
  await openClub(page, "River Rowing Club");
  await tab(page, "members");
  const rows = page.getByTestId("member-row");
  const mira = rows.filter({ hasText: "Mira Oar" });
  await expect(mira.getByTestId("member-make-coach")).toBeVisible();
  await expect(mira.getByTestId("member-make-admin")).toHaveCount(0); // an admin can't mint another admin
  await expect(rows.filter({ hasText: "Riley Owner" }).getByTestId("member-remove")).toHaveCount(0); // and can't touch the owner
  await mira.getByTestId("member-remove").tap();
  const sheet = page.getByTestId("remove-sheet");
  await expect(sheet.getByTestId("remove-sheet-submit")).toBeDisabled(); // no reason, no removal
  await sheet.getByTestId("remove-sheet-reason").fill("Repeatedly ignored the safety briefing");
  await aboveNav(page, sheet.getByTestId("remove-sheet-submit"));
  await sheet.getByTestId("remove-sheet-submit").tap();
  await expect(sheet).toBeHidden();
  await expect(page.getByTestId("club-members")).not.toContainText("Mira Oar");
  await tab(page, "manage");
  await expect(page.getByTestId("club-audit")).toContainText("Removed");
  await expect(page.getByTestId("club-audit")).toContainText("Repeatedly ignored the safety briefing");
});

test("an athlete sees no administrative controls", async ({ page }) => {
  await page.goto("/clubs?mock=1&role=athlete");
  await openClub(page, "River Rowing Club");
  await expect(page.getByTestId("club-tab-manage")).toHaveCount(0);
  await tab(page, "members");
  await expect(page.getByTestId("member-remove")).toHaveCount(0);
  await expect(page.getByTestId("member-make-coach")).toHaveCount(0);
  await tab(page, "news");
  await expect(page.getByTestId("news-new")).toHaveCount(0);
  await tab(page, "calendar");
  await expect(page.getByTestId("calendar-plan")).toHaveCount(0);
});

test("reporting a member says who sees it: a moderator, never the club's staff", async ({ page }) => {
  await page.goto("/clubs?mock=1&role=athlete");
  await openClub(page, "River Rowing Club");
  await tab(page, "members");
  await page.getByTestId("member-row").filter({ hasText: "Tom Catch" }).getByTestId("member-report").tap();
  const sheet = page.getByTestId("report-sheet");
  await expect(sheet).toContainText("platform moderator");
  await expect(sheet).toContainText("not told who reported");
  await aboveNav(page, sheet.getByTestId("report-submit"));
  await sheet.getByTestId("report-submit").tap();
  await expect(sheet.getByTestId("report-done")).toContainText("not told who reported");
});

test("blocking hides a member's name from your list only", async ({ page }) => {
  await page.goto("/clubs?mock=1&role=athlete");
  await openClub(page, "River Rowing Club");
  await tab(page, "members");
  const tom = page.getByTestId("member-row").filter({ hasText: "Tom Catch" });
  await tom.getByTestId("member-block").tap();
  await expect(page.getByTestId("member-row").filter({ hasText: "Blocked member" })).toHaveCount(1);
  await expect(page.getByTestId("club-members")).not.toContainText("Tom Catch");
});

// ---------------------------------------------------------------- team training

test("a team session can be marked 'I took part' and undone; the club learns a count, not the workout", async ({ page }) => {
  await page.goto("/clubs?mock=1&role=athlete");
  await openClub(page, "River Rowing Club");
  await tab(page, "calendar");
  const row = page.getByTestId("session-row").filter({ hasText: "Steady 60" });
  await expect(row.getByTestId("session-count")).toHaveText("5 took part");
  await expect(page.getByText("These are plans for the club, not workouts")).toBeVisible();
  await row.getByTestId("session-took-part").tap();
  const sheet = page.getByTestId("link-sheet");
  await expect(sheet).toContainText("learns only that you took part");
  await expect(sheet.getByTestId("link-share")).not.toBeChecked(); // numbers are off unless you choose to share them
  await page.keyboard.press("Escape");
  await expect(sheet).toBeHidden();
  await noHorizontalOverflow(page);
});

test("team totals stay hidden until enough members share a number", async ({ page }) => {
  await page.goto("/clubs?mock=1");
  await openClub(page, "River Rowing Club");
  await expect(page.getByTestId("club-summary-distance")).toHaveText("Hidden");
  await expect(page.getByTestId("club-summary")).toBeVisible();
  await expect(page.getByTestId("club-overview")).toContainText("at least 3 members chose to share a number");
});

// ---------------------------------------------------------------- challenges

test("a challenge states its rules in plain words, ranks ties together, and can be joined and left", async ({ page }) => {
  await page.goto("/clubs?mock=1&role=athlete");
  await openClub(page, "River Rowing Club");
  await tab(page, "challenges");
  await page.getByTestId("challenge-link").first().tap();
  await expect(page.getByTestId("challenge-page")).toBeVisible();
  const rules = page.getByTestId("challenge-rules");
  await expect(rules).toContainText("Equal scores share a rank");
  await expect(rules).toContainText("training harder than that earns nothing extra");
  await expect(rules).toContainText("Nothing about weight, calories, recovery or sleep is used or shown");
  const ranks = await page.getByTestId("standing-row").locator("span.font-mono-nums").first().innerText();
  expect(ranks).toBe("1");
  const all = (await page.getByTestId("standing-row").allInnerTexts()).map((t) => t.split("\n")[0]);
  expect(all).toEqual(["1", "2", "2", "4"]); // standard competition ranking
  await page.getByTestId("challenge-join").tap();
  await expect(page.getByTestId("challenge-my-value")).toHaveText("8.0 km");
  await expect(page.getByTestId("standing-row").filter({ hasText: "(you)" })).toBeVisible();
  await page.getByTestId("challenge-leave").tap();
  await expect(page.getByTestId("challenge-join")).toBeVisible();
  await expect(page.getByTestId("standing-row").filter({ hasText: "(you)" })).toHaveCount(0);
  await noHorizontalOverflow(page);
});

test("creating a challenge without a goal is refused with what to change", async ({ page }) => {
  await page.goto("/clubs?mock=1&role=coach");
  await openClub(page, "River Rowing Club");
  await tab(page, "challenges");
  await page.getByTestId("challenge-new").tap();
  const sheet = page.getByTestId("challenge-sheet");
  await expect(sheet).toContainText("extra volume never earns more");
  await sheet.getByTestId("challenge-title").fill("Dawn Cup");
  await aboveNav(page, sheet.getByTestId("challenge-submit"));
  await sheet.getByTestId("challenge-submit").tap();
  await expect(sheet.getByRole("alert")).toContainText("set a goal");
  await sheet.getByTestId("challenge-goal").fill("80");
  await sheet.getByTestId("challenge-submit").tap();
  await expect(sheet).toBeHidden();
  await expect(page.getByTestId("club-challenges")).toContainText("Dawn Cup");
});

test("a consistency challenge lets you excuse a week without giving a reason", async ({ page }) => {
  await page.goto("/clubs?mock=1&role=coach");
  await openClub(page, "River Rowing Club");
  await tab(page, "challenges");
  await page.getByTestId("challenge-new").tap();
  const sheet = page.getByTestId("challenge-sheet");
  await sheet.getByTestId("challenge-title").fill("Steady Weeks");
  await sheet.getByTestId("challenge-metric").selectOption("consistency");
  await expect(sheet.getByTestId("challenge-target")).toBeVisible();
  await expect(sheet).toContainText("More than this earns nothing");
  await sheet.getByTestId("challenge-submit").tap();
  await expect(sheet).toBeHidden();
  await page.getByTestId("challenge-link").filter({ hasText: "Steady Weeks" }).tap();
  await expect(page.getByTestId("challenge-rules")).toContainText("Equal scores share a rank");
});

// ---------------------------------------------------------------- the results board

test("the club board ranks verified results and lists the rest, labelled, below", async ({ page }) => {
  await page.goto("/clubs?mock=1&role=athlete");
  await openClub(page, "River Rowing Club");
  await tab(page, "board");
  await expect(page.getByTestId("board-context")).toContainText("2,000 m");
  await expect(page.getByTestId("board-row").first()).toContainText("Mira Oar");
  await expect(page.getByTestId("board-row").first().getByTestId("verification-verified")).toContainText("Verified");
  await expect(page.getByTestId("board-unverified")).toContainText("Provider-linked");
  await expect(page.getByTestId("board-unverified")).toContainText("Not ranked");
  await expect(page.getByText("Members choose what they share here")).toBeVisible();
  await noHorizontalOverflow(page);
});

// ---------------------------------------------------------------- invites

test("an invite link shows the club and its rules, and needs the rules accepted before joining", async ({ page }) => {
  await page.goto("/clubs/join?mock=1#mock-token-athlete");
  await expect(page.getByTestId("club-join-page")).toContainText("You're invited to River Rowing Club");
  await expect(page.getByTestId("club-join-page")).toContainText("Be kind. Row hard. Respect your coach.");
  await expect(page.getByTestId("join-go")).toBeDisabled();
  await page.getByTestId("join-accept-rules").check();
  await page.getByTestId("join-go").tap();
  await expect(page.getByTestId("club-header")).toBeVisible(); // a valid invite to an adult invite-club joins directly
  await noHorizontalOverflow(page);
});

test("a junior invite says a coach approves, and the request waits", async ({ page }) => {
  await page.goto("/clubs/join?mock=1#mock-token-junior");
  await expect(page.getByTestId("join-junior-note")).toContainText("A coach will approve your request");
  await expect(page.getByTestId("join-junior-note")).toContainText("parent or guardian");
});

test("an expired or revoked invite says so plainly", async ({ page }) => {
  await page.goto("/clubs/join?mock=1#bad");
  await expect(page.getByTestId("club-join-page")).toContainText("isn't valid any more");
});

test("pasting a link works and the token never appears in the address bar after it is used", async ({ page }) => {
  await page.goto("/clubs/join?mock=1");
  await page.getByTestId("join-paste").fill("https://catch.example/clubs/join#mock-token-athlete");
  await page.getByTestId("join-paste-go").tap();
  await expect(page.getByTestId("club-join-page")).toContainText("River Rowing Club");
  await page.getByTestId("join-accept-rules").check();
  await page.getByTestId("join-go").tap();
  await expect(page.getByTestId("club-header")).toBeVisible();
  expect(page.url()).not.toContain("mock-token");
});

test("a staff member creates an invite link that is shown once", async ({ page }) => {
  await page.goto("/clubs?mock=1&role=coach");
  await openClub(page, "River Rowing Club");
  await tab(page, "manage");
  await page.getByTestId("invite-new").tap();
  const sheet = page.getByTestId("invite-sheet");
  await expect(sheet.getByTestId("invite-role").locator("option")).toHaveCount(1); // a coach can invite athletes, not coaches
  await aboveNav(page, sheet.getByTestId("invite-create"));
  await sheet.getByTestId("invite-create").tap();
  await expect(sheet.getByTestId("invite-link")).toHaveValue(/\/clubs\/join#mock-token-athlete/);
  await expect(sheet).toContainText("shown once");
});

// ---------------------------------------------------------------- junior clubs

test("a young athlete sees only published posts, no controls, and is told how the club is run", async ({ page }) => {
  await page.goto("/clubs?mock=1&junior=1&jrole=athlete");
  await openClub(page, "Junior Squad");
  await expect(page.getByTestId("junior-badge").first()).toBeVisible();
  await expect(page.getByTestId("junior-note")).toContainText("no private messages");
  await tab(page, "news");
  await expect(page.getByTestId("post-row")).toHaveCount(1);
  await expect(page.getByTestId("post-row")).toContainText("Welcome to the squad");
  await expect(page.getByTestId("post-row")).not.toContainText("Regatta weekend"); // the held post is invisible to athletes
  await expect(page.getByTestId("news-new")).toHaveCount(0);
  await expect(page.getByTestId("club-tab-manage")).toHaveCount(0);
  await noHorizontalOverflow(page);
});

test("in a junior club an admin's post waits for a coach, and an admin can't approve it", async ({ page }) => {
  await page.goto("/clubs?mock=1&junior=1&jrole=admin");
  await openClub(page, "Junior Squad");
  await tab(page, "news");
  const held = page.getByTestId("post-row").filter({ hasText: "Regatta weekend" });
  await expect(held.getByTestId("post-status")).toContainText("Waiting for a coach");
  await expect(held.getByTestId("post-approve")).toHaveCount(0); // an admin can't approve
  await page.getByTestId("news-new").tap();
  const sheet = page.getByTestId("post-sheet");
  await expect(sheet).toContainText("A coach approves it before members see it");
  await sheet.getByTestId("post-title").fill("Kit list");
  await sheet.getByTestId("post-body").fill("Bring a water bottle.");
  await aboveNav(page, sheet.getByTestId("post-submit"));
  await sheet.getByTestId("post-submit").tap();
  await expect(sheet.getByTestId("post-pending")).toContainText("coach approves a post before members see it");
});

test("the owner of a junior club counts as a coach: their post goes out and they approve a held one", async ({ page }) => {
  await page.goto("/clubs?mock=1&junior=1&jrole=owner");
  await openClub(page, "Junior Squad");
  await tab(page, "news");
  await page.getByTestId("news-new").tap();
  const sheet = page.getByTestId("post-sheet");
  await sheet.getByTestId("post-title").fill("Kit list");
  await sheet.getByTestId("post-body").fill("Bring a water bottle. See www.example.com");
  await sheet.getByTestId("post-submit").tap();
  await expect(sheet.getByTestId("post-pending")).toHaveCount(0);
  await expect(page.getByTestId("post-sheet")).toHaveCount(0);
  await expect(page.getByTestId("post-row").filter({ hasText: "Kit list" }).getByTestId("post-status")).toHaveCount(0); // published, links allowed
  await page.getByTestId("post-row").filter({ hasText: "Regatta weekend" }).getByTestId("post-approve").tap();
  await expect(page.getByTestId("post-row").filter({ hasText: "Regatta weekend" }).getByTestId("post-status")).toHaveCount(0);
});

test("a coach approves a held post and a young member's request", async ({ page }) => {
  await page.goto("/clubs?mock=1&junior=1&jrole=coach");
  await openClub(page, "Junior Squad");
  await tab(page, "news");
  const held = page.getByTestId("post-row").filter({ hasText: "Regatta weekend" });
  await held.getByTestId("post-approve").tap();
  await expect(page.getByTestId("post-row").filter({ hasText: "Regatta weekend" }).getByTestId("post-status")).toHaveCount(0); // now published
  await tab(page, "manage");
  const req = page.getByTestId("request-row").filter({ hasText: "Rae Hopeful" });
  await expect(req).toContainText("Under 19");
  await expect(req).toContainText("guardian agreed");
  await req.getByTestId("request-approve").tap();
  await expect(page.getByTestId("request-row")).toHaveCount(0);
});

test("an owner approves a young athlete's request, and can add a logo to a junior club", async ({ page }) => {
  await page.goto("/clubs?mock=1&junior=1&jrole=owner");
  await openClub(page, "Junior Squad");
  await tab(page, "manage");
  await expect(page.getByTestId("logo-input")).toHaveCount(1);
  const req = page.getByTestId("request-row").filter({ hasText: "Rae Hopeful" });
  await req.getByTestId("request-approve").tap();
  await expect(page.getByTestId("request-row")).toHaveCount(0);
});

test("an admin of a junior club cannot decide a young athlete's request", async ({ page }) => {
  await page.goto("/clubs?mock=1&junior=1&jrole=admin");
  await openClub(page, "Junior Squad");
  await tab(page, "manage");
  const req = page.getByTestId("request-row").filter({ hasText: "Rae Hopeful" });
  await expect(req.getByTestId("request-needs-coach")).toContainText("only a coach or the owner approves a young member");
  await expect(req.getByTestId("request-approve")).toHaveCount(0);
});

test("starting a junior club explains the rules and fixes the settings", async ({ page }) => {
  await page.goto("/clubs?mock=1");
  await page.getByTestId("clubs-start").tap();
  const sheet = page.getByTestId("create-club-sheet");
  await sheet.getByTestId("club-name").fill("Under Nineteens");
  await sheet.getByTestId("club-audience").selectOption("junior");
  await expect(sheet.getByTestId("junior-explainer")).toContainText("coach approves each one");
  await expect(sheet.getByTestId("club-visibility")).toHaveCount(0); // visibility and join policy aren't choices for a junior club
  await expect(sheet.getByTestId("club-join-policy")).toHaveCount(0);
  await aboveNav(page, sheet.getByTestId("club-create"));
  await sheet.getByTestId("club-create").tap();
  await expect(page.getByTestId("club-header")).toContainText("Under Nineteens");
  await expect(page.getByTestId("junior-badge").first()).toBeVisible();
});

// ---------------------------------------------------------------- moderation and navigation

test("a moderator sees reported clubs, never who reported, and every action needs a reason", async ({ page }) => {
  await page.goto("/settings/moderation?mock=1&mod=1");
  const queue = page.getByTestId("club-mod-queue");
  await expect(queue).toContainText("River Rowing Club");
  await expect(queue).toContainText("Junior Squad · junior");
  await expect(queue).not.toContainText("reporter");
  await queue.getByTestId("club-mod-open").first().tap();
  const detail = page.getByTestId("club-mod-detail");
  await expect(detail).toBeVisible();
  await detail.getByTestId("club-mod-suspend").tap();
  await expect(detail.getByRole("alert")).toContainText("A reason is required.");
  await detail.getByTestId("club-mod-reason").fill("Under review after two reports");
  await detail.getByTestId("club-mod-suspend").tap();
  await expect(page.getByTestId("club-mod-detail")).toHaveCount(0);
});

test("Settings links to Clubs, and the old leaderboard club form points there", async ({ page }) => {
  await page.goto("/settings?mock=1");
  await page.getByTestId("settings-clubs").tap();
  await expect(page.getByTestId("clubs-page")).toBeVisible();
  await noHorizontalOverflow(page);
});

test("the leaderboard settings page no longer takes a join code and links to clubs instead", async ({ page }) => {
  await page.goto("/settings/leaderboards?mock=1");
  await page.getByTestId("lb-mode-anonymous").tap();
  await page.getByTestId("lb-age13").check();
  await page.getByTestId("lb-confirm").check();
  await page.getByTestId("lb-optin").tap();
  await expect(page.getByTestId("lb-club-code-input")).toHaveCount(0);
  await expect(page.getByTestId("lb-clubs-link")).toBeVisible();
});
