import * as Dialog from "@radix-ui/react-dialog";
import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../../lib/auth";
import { cn } from "../../lib/cn";
import { GROUP_LABEL, moreGroups, tabFor, type TabId } from "../../lib/navigation";
import { useTheme } from "../../lib/theme";
import { SheetContent, SheetHeader } from "../ui/Sheet";
import { CalendarIcon, CoachIcon, LogoutIcon, MoonIcon, MoreIcon, SunIcon, TodayIcon, TrainIcon } from "./icons";

// Session 35: four destinations and More (was eight squeezed tabs). The calendar's tab keeps the short label "Plan" — "Calendar"
// clips at 11px on 360–375px phones (DESIGN.md, calendar.spec). Every other destination is one tap away in the More sheet.
const TABS: { id: Exclude<TabId, "more">; to: string; label: string; Icon: typeof TodayIcon }[] = [
  { id: "today", to: "/", label: "Today", Icon: TodayIcon },
  { id: "plan", to: "/calendar", label: "Plan", Icon: CalendarIcon },
  { id: "train", to: "/train", label: "Train", Icon: TrainIcon },
  { id: "coach", to: "/coach", label: "Coach", Icon: CoachIcon },
];

const groups = moreGroups();

function TabInner({ active, label, Icon }: { active: boolean; label: string; Icon: typeof TodayIcon }) {
  return (
    <>
      <span
        aria-hidden
        className={cn(
          "flex h-6 w-11 items-center justify-center rounded-full transition-colors duration-200",
          active ? "bg-accent-soft text-accent" : "text-text-tertiary group-hover:text-text-secondary",
        )}
      >
        <Icon className="h-5 w-5 shrink-0" />
      </span>
      <span className={cn("w-full truncate text-center text-[11px] leading-none", active ? "font-semibold text-text-primary" : "text-text-tertiary")}>{label}</span>
    </>
  );
}

export function BottomNav() {
  const { pathname } = useLocation();
  const current = tabFor(pathname);
  const [moreOpen, setMoreOpen] = useState(false);
  const { theme, toggle } = useTheme();
  const { logout, status } = useAuth();

  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-20 border-t border-border/80 bg-surface/90 backdrop-blur-lg"
      style={{ paddingBottom: "env(safe-area-inset-bottom)", paddingLeft: "env(safe-area-inset-left)", paddingRight: "env(safe-area-inset-right)" }}
      aria-label="Primary"
    >
      <ul className="mx-auto flex max-w-xl items-stretch justify-between px-1">
        {TABS.map(({ id, to, label, Icon }) => (
          <li key={id} className="min-w-0 flex-1">
            <Link
              to={to}
              aria-current={current === id ? "page" : undefined}
              className="group flex min-h-11 min-w-0 flex-col items-center justify-center gap-1 px-0.5 pb-1.5 pt-1.5"
            >
              <TabInner active={current === id} label={label} Icon={Icon} />
            </Link>
          </li>
        ))}
        <li className="min-w-0 flex-1">
          <Dialog.Root open={moreOpen} onOpenChange={setMoreOpen}>
            <Dialog.Trigger asChild>
              <button type="button" aria-label="More" className="group flex min-h-11 w-full min-w-0 flex-col items-center justify-center gap-1 px-0.5 pb-1.5 pt-1.5">
                <TabInner active={current === "more" || moreOpen} label="More" Icon={MoreIcon} />
              </button>
            </Dialog.Trigger>
            <SheetContent width="md" data-testid="more-sheet">
              <SheetHeader title="More" description="Everything else in Catch." onClose />
              <nav aria-label="More destinations" className="flex flex-col gap-5">
                {groups.map((g) => (
                  <div key={g.id}>
                    <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.09em] text-text-tertiary">{GROUP_LABEL[g.id]}</p>
                    <ul className="grid grid-cols-2 gap-2">
                      {g.items.map(({ to, label, Icon, blurb }) => (
                        <li key={to} className="min-w-0">
                          <Link
                            to={to}
                            onClick={() => setMoreOpen(false)}
                            className="flex h-full min-h-14 min-w-0 items-start gap-2.5 rounded-md border border-border bg-surface-2/60 p-3 transition-colors hover:border-border-strong hover:bg-surface-2"
                          >
                            <Icon className="mt-0.5 h-5 w-5 shrink-0 text-accent" />
                            <span className="min-w-0">
                              <span className="block text-sm font-medium text-text-primary">{label}</span>
                              {blurb && <span className="mt-0.5 block text-xs leading-snug text-text-tertiary">{blurb}</span>}
                            </span>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
                <div className="flex flex-wrap gap-2 border-t border-border pt-4">
                  <button type="button" onClick={toggle} className="flex min-h-11 items-center gap-2 rounded-md border border-border px-3 text-sm font-medium text-text-secondary hover:text-text-primary">
                    {theme === "dark" ? <SunIcon className="h-5 w-5" /> : <MoonIcon className="h-5 w-5" />}
                    {theme === "dark" ? "Light theme" : "Dark theme"}
                  </button>
                  {status === "authed" && (
                    <button
                      type="button"
                      onClick={() => {
                        setMoreOpen(false);
                        logout();
                      }}
                      className="flex min-h-11 items-center gap-2 rounded-md border border-border px-3 text-sm font-medium text-text-secondary hover:text-text-primary"
                    >
                      <LogoutIcon className="h-5 w-5" />
                      Log out
                    </button>
                  )}
                </div>
              </nav>
            </SheetContent>
          </Dialog.Root>
        </li>
      </ul>
    </nav>
  );
}
