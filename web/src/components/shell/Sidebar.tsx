import { NavLink } from "react-router-dom";
import { useAuth } from "../../lib/auth";
import { useTheme } from "../../lib/theme";
import { BodyIcon, CoachIcon, LogoutIcon, MoonIcon, NutritionIcon, SettingsIcon, SunIcon, TodayIcon, TrendsIcon, WorkoutsIcon } from "./icons";

const ITEMS = [
  { to: "/", label: "Today", Icon: TodayIcon },
  { to: "/workouts", label: "Workouts", Icon: WorkoutsIcon },
  { to: "/trends", label: "Trends", Icon: TrendsIcon },
  { to: "/body", label: "Body", Icon: BodyIcon },
  { to: "/nutrition", label: "Nutrition", Icon: NutritionIcon },
  { to: "/coach", label: "Coach", Icon: CoachIcon },
  { to: "/settings", label: "Settings", Icon: SettingsIcon },
];

export function Sidebar() {
  const { theme, toggle } = useTheme();
  const { logout, status } = useAuth();

  return (
    <aside className="sticky top-0 hidden h-dvh w-56 shrink-0 flex-col justify-between border-r border-border px-4 py-5 lg:flex">
      <div>
        <span className="font-mono-nums block px-2 text-sm font-semibold tracking-wide text-text-primary">CATCH</span>
        <ul className="mt-6 flex flex-col gap-1">
          {ITEMS.map(({ to, label, Icon }) => (
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
