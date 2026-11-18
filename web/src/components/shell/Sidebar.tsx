import { NavLink } from "react-router-dom";
import { isMock } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { isPublic } from "../../lib/deployment";
import { useTheme } from "../../lib/theme";
import { BodyIcon, CalendarIcon, ClubsIcon, CoachIcon, FeedbackIcon, GymIcon, LeaderboardsIcon, LibraryIcon, LogoutIcon, MoonIcon, NutritionIcon, RoutesIcon, SettingsIcon, SunIcon, TestsIcon, TodayIcon, TrendsIcon, WorkoutsIcon } from "./icons";

const ITEMS = [
  { to: "/", label: "Today", Icon: TodayIcon },
  // Session 21: the same destination as the bottom nav's Calendar tab; Workouts keeps its own entry here.
  { to: "/calendar", label: "Calendar", Icon: CalendarIcon },
  { to: "/workouts", label: "Workouts", Icon: WorkoutsIcon },
  { to: "/library", label: "Library", Icon: LibraryIcon },
  { to: "/feedback", label: "Feedback", Icon: FeedbackIcon },
  { to: "/gym", label: "Gym", Icon: GymIcon },
  // Session 15 Part C — the bottom nav is already tight at 8 items (DESIGN.md), so the Test
  // Center's only nav entry point is here on desktop, plus a link from the Workouts page
  // header on mobile (same pattern Duplicates/Muscle-readiness already use).
  { to: "/tests", label: "Tests", Icon: TestsIcon },
  // Session 20 — same no-bottom-nav-slot pattern as Tests: desktop sidebar plus a Workouts header link.
  { to: "/routes", label: "Routes", Icon: RoutesIcon },
  { to: "/trends", label: "Trends", Icon: TrendsIcon },
  { to: "/body", label: "Body", Icon: BodyIcon },
  { to: "/nutrition", label: "Nutrition", Icon: NutritionIcon },
  { to: "/coach", label: "Coach", Icon: CoachIcon },
  { to: "/settings", label: "Settings", Icon: SettingsIcon },
];

// Session 26: leaderboards exist only on the public build (no bottom-nav slot, same pattern as Tests/Routes); the mock shows them too.
const LEADERBOARDS_ITEM = { to: "/leaderboards", label: "Leaderboards", Icon: LeaderboardsIcon };
// Session 27: clubs, same pattern (public build and the mock only; the bottom nav stays at eight).
const CLUBS_ITEM = { to: "/clubs", label: "Clubs", Icon: ClubsIcon };

export function Sidebar() {
  const items = isPublic || isMock ? [...ITEMS.slice(0, -1), CLUBS_ITEM, LEADERBOARDS_ITEM, ITEMS[ITEMS.length - 1]] : ITEMS;
  const { theme, toggle } = useTheme();
  const { logout, status } = useAuth();

  return (
    <aside className="sticky top-0 hidden h-dvh w-56 shrink-0 flex-col justify-between border-r border-border px-4 py-5 lg:flex">
      <div>
        <span className="font-mono-nums block px-2 text-sm font-semibold tracking-wide text-text-primary">CATCH</span>
        <ul className="mt-6 flex flex-col gap-1">
          {items.map(({ to, label, Icon }) => (
            <li key={to}>
              <NavLink
                to={to}
                end={to === "/"}
                className={({ isActive }) =>
                  `flex min-h-11 items-center gap-3 rounded-md px-2.5 text-sm transition-colors ${
                    isActive ? "bg-surface-2 text-accent" : "text-text-tertiary hover:text-text-secondary"
                  }`
                }
              >
                <Icon className="h-5 w-5 shrink-0" />
                {label}
              </NavLink>
            </li>
          ))}
        </ul>
      </div>

      <div className="flex flex-col gap-1">
        <button
          type="button"
          onClick={toggle}
          className="flex min-h-11 items-center gap-3 rounded-md px-2.5 text-sm text-text-tertiary transition-colors hover:text-text-secondary"
        >
          {theme === "dark" ? <SunIcon className="h-5 w-5" /> : <MoonIcon className="h-5 w-5" />}
          {theme === "dark" ? "Light theme" : "Dark theme"}
        </button>
        {status === "authed" && (
          <button
            type="button"
            onClick={() => logout()}
            className="flex min-h-11 items-center gap-3 rounded-md px-2.5 text-sm text-text-tertiary transition-colors hover:text-text-secondary"
          >
            <LogoutIcon className="h-5 w-5" />
            Log out
          </button>
        )}
      </div>
    </aside>
  );
}
