import { NavLink, useLocation } from "react-router-dom";
import { BodyIcon, CalendarIcon, CoachIcon, GymIcon, NutritionIcon, SettingsIcon, TodayIcon, TrendsIcon } from "./icons";

// "Fuel"/"Gym" rather than "Nutrition"/"Workouts" repeated — at 390px/8 items there's even
// less text width per item than session 13's 7-item note already flagged; screenshot this at
// 390px before lengthening any label back (see PLAN.md's session 13 and session 14 notes).
const ITEMS: { to: string; label: string; Icon: typeof TodayIcon; alsoActive?: string[] }[] = [
  { to: "/", label: "Today", Icon: TodayIcon },
  // Session 21: the calendar took the old "Log" slot. The label is "Plan", not "Calendar": at 11px that clips at
  // 375px and 360px wide (measured), the same constraint that made the others "Fuel"/"Gym". The page, the sidebar
  // entry and the URL are all "Calendar". (Workouts stays one tap away from Calendar and in the
  // desktop sidebar). The tab also reads active on /workouts*, since those pages are reached from it.
  { to: "/calendar", label: "Plan", Icon: CalendarIcon, alsoActive: ["/workouts"] },
  { to: "/gym", label: "Gym", Icon: GymIcon },
  { to: "/trends", label: "Trends", Icon: TrendsIcon },
  { to: "/body", label: "Body", Icon: BodyIcon },
  { to: "/nutrition", label: "Fuel", Icon: NutritionIcon },
  { to: "/coach", label: "Coach", Icon: CoachIcon },
  { to: "/settings", label: "Settings", Icon: SettingsIcon },
];

export function BottomNav() {
  const { pathname } = useLocation();
  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-20 border-t border-border bg-surface/95 backdrop-blur sm:static sm:border-t-0 sm:bg-transparent"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      aria-label="Primary"
    >
      <ul className="mx-auto flex max-w-3xl items-stretch justify-between sm:justify-center sm:gap-2">
        {ITEMS.map(({ to, label, Icon, alsoActive }) => {
          const forced = alsoActive?.some((p) => pathname === p || pathname.startsWith(`${p}/`)) ?? false;
          return (
          <li key={to} className="min-w-0 flex-1 sm:flex-none">
            <NavLink
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                `flex min-h-11 min-w-0 flex-col items-center justify-center gap-1 px-0.5 py-2 text-[11px] transition-colors sm:flex-row sm:gap-2 sm:px-3 sm:rounded-md sm:text-xs ${
                  isActive || forced ? "text-accent" : "text-text-tertiary hover:text-text-secondary"
                }`
              }
            >
              <Icon className="h-5 w-5 shrink-0" />
              <span className="w-full truncate text-center leading-none">{label}</span>
            </NavLink>
          </li>
          );
        })}
      </ul>
    </nav>
  );
}
