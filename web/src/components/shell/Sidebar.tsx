import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../../lib/auth";
import { cn } from "../../lib/cn";
import { activeSidebarPath, GROUP_LABEL, SETTINGS_ITEM, sidebarGroups, type NavItem } from "../../lib/navigation";
import { useTheme } from "../../lib/theme";
import { Logomark, LogoutIcon, MoonIcon, SunIcon } from "./icons";

const groups = sidebarGroups();
const sidebarItems = [...groups.flatMap((g) => g.items), SETTINGS_ITEM];

function Item({ item, active }: { item: NavItem; active: boolean }) {
  const { to, label, Icon } = item;
  return (
    <Link
      to={to}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group relative flex min-h-10 items-center gap-3 rounded-md px-2.5 text-sm font-medium transition-colors duration-150",
        active ? "bg-accent-soft text-text-primary" : "text-text-secondary hover:bg-surface-2/70 hover:text-text-primary",
      )}
    >
      {active && <span aria-hidden className="absolute -left-3 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-accent" />}
      <Icon className={cn("h-[18px] w-[18px] shrink-0", active ? "text-accent" : "text-text-tertiary group-hover:text-text-secondary")} />
      {label}
    </Link>
  );
}

/** Desktop navigation (lg and up): grouped destinations, Settings and the account controls pinned to the foot. */
export function Sidebar() {
  const { pathname } = useLocation();
  const { theme, toggle } = useTheme();
  const { logout, status } = useAuth();
  const active = activeSidebarPath(pathname, sidebarItems);

  return (
    <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r border-border/80 bg-surface/40 px-3 py-5 backdrop-blur-sm lg:flex">
      <Link to="/" className="mb-6 flex items-center gap-2.5 px-2.5" aria-label="Catch — Today">
        <Logomark className="h-7 w-7" />
        <span className="text-[15px] font-semibold tracking-[0.14em] text-text-primary">CATCH</span>
      </Link>
      <nav aria-label="Main" className="min-h-0 flex-1 overflow-y-auto pl-3 -ml-3">
        {groups.map((g) => (
          <div key={g.id} className="mb-5">
            <p className="mb-1.5 px-2.5 text-[11px] font-semibold uppercase tracking-[0.09em] text-text-tertiary">{GROUP_LABEL[g.id]}</p>
            <ul className="flex flex-col gap-0.5">
              {g.items.map((item) => (
                <li key={item.to}>
                  <Item item={item} active={active === item.to} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className="flex shrink-0 flex-col gap-0.5 border-t border-border/80 pt-3 pl-3 -ml-3">
        <Item item={SETTINGS_ITEM} active={active === SETTINGS_ITEM.to} />
        <button
          type="button"
          onClick={toggle}
          className="flex min-h-10 items-center gap-3 rounded-md px-2.5 text-sm font-medium text-text-secondary transition-colors hover:bg-surface-2/70 hover:text-text-primary"
        >
          {theme === "dark" ? <SunIcon className="h-[18px] w-[18px] text-text-tertiary" /> : <MoonIcon className="h-[18px] w-[18px] text-text-tertiary" />}
          {theme === "dark" ? "Light theme" : "Dark theme"}
        </button>
        {status === "authed" && (
          <button
            type="button"
            onClick={() => logout()}
            className="flex min-h-10 items-center gap-3 rounded-md px-2.5 text-sm font-medium text-text-secondary transition-colors hover:bg-surface-2/70 hover:text-text-primary"
          >
            <LogoutIcon className="h-[18px] w-[18px] text-text-tertiary" />
            Log out
          </button>
        )}
      </div>
    </aside>
  );
}
