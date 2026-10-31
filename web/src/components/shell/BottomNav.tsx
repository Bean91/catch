import { NavLink } from "react-router-dom";
import { CoachIcon, SettingsIcon, TodayIcon, TrendsIcon, WorkoutsIcon } from "./icons";

const ITEMS = [
  { to: "/", label: "Today", Icon: TodayIcon },
  { to: "/workouts", label: "Workouts", Icon: WorkoutsIcon },
  { to: "/trends", label: "Trends", Icon: TrendsIcon },
  { to: "/coach", label: "Coach", Icon: CoachIcon },
  { to: "/settings", label: "Settings", Icon: SettingsIcon },
];

export function BottomNav() {
  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-20 border-t border-border bg-surface/95 backdrop-blur sm:static sm:border-t-0 sm:bg-transparent"
      aria-label="Primary"
    >
      <ul className="mx-auto flex max-w-3xl items-stretch justify-between sm:justify-center sm:gap-2">
        {ITEMS.map(({ to, label, Icon }) => (
          <li key={to} className="flex-1 sm:flex-none">
            <NavLink
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                `flex min-h-11 flex-col items-center justify-center gap-1 px-2 py-2 text-xs transition-colors sm:flex-row sm:gap-2 sm:rounded-md sm:px-3 ${
                  isActive ? "text-accent" : "text-text-tertiary hover:text-text-secondary"
                }`
              }
            >
              <Icon className="h-5 w-5" />
              <span>{label}</span>
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
