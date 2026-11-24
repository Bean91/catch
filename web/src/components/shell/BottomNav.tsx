import * as Dialog from "@radix-ui/react-dialog";
import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../../lib/auth";
import { cn } from "../../lib/cn";
import { GROUP_LABEL, moreGroups, tabFor, type TabId } from "../../lib/navigation";
import { useTheme } from "../../lib/theme";
import { SheetContent, SheetHeader } from "../ui/Sheet";
import { CalendarIcon, CoachIcon, LogoutIcon, MoonIcon, MoreIcon, SunIcon, TodayIcon, TrainIcon } from "./icons";
import { buttonClass } from "../ui/Button";

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
          active ? "text-accent" : "text-text-secondary group-hover:text-text-primary",
        )}
      >
        <Icon className="h-5 w-5 shrink-0" />
      </span>
      <span className={cn("w-full truncate text-center text-[11px] leading-none", active ? "font-semibold text-text-primary" : "text-text-secondary")}>{label}</span>
    </>
  );
}

const TAB_INDEX: Record<TabId, number> = { today: 0, plan: 1, train: 2, coach: 3, more: 4 };

export function BottomNav() {
  const { pathname } = useLocation();
  const current = tabFor(pathname);
  const [moreOpen, setMoreOpen] = useState(false);
  const { theme, toggle } = useTheme();
  const { logout, status } = useAuth();
  const lensIndex = moreOpen ? TAB_INDEX.more : TAB_INDEX[current];

  return (
    // Session 37 (DESIGN.md "Mobile glass"): a floating glass capsule, inset from the screen edges and 8px above the home indicator,
    // at most 560px wide so a landscape phone or a tablet gets a centred bar rather than a stretched one. --shell-bottom (60px) is its
    // 52px height plus the 8px gap; pages pad themselves from it plus the safe area, exactly the capsule's footprint. The bg/blur
    // utilities are the fallback look if glass.css ever doesn't apply (the material overrides them below lg).
    <nav
      className="glass-primary fixed bottom-[calc(env(safe-area-inset-bottom)+8px)] left-[max(12px,calc(env(safe-area-inset-left)+8px))] right-[max(12px,calc(env(safe-area-inset-right)+8px))] z-20 mx-auto max-w-[560px] rounded-2xl border border-border/70 bg-surface/90 backdrop-blur-lg"
      aria-label="Primary"
    >
      <ul className="relative flex h-[52px] items-stretch justify-between px-1">
        {/* One indicator slides under the active slot. The five slots are equal (flex-1), so a fifth of the row moved by whole
            widths lands exactly on each; the active tab also changes its icon and label colour, so the lens never carries state alone. */}
        <li aria-hidden className="pointer-events-none absolute inset-y-1 left-1 w-[calc((100%-0.5rem)/5)]">
          <span
            data-accent
            data-testid="nav-lens"
            className="glass-lens block h-full rounded-xl transition-transform duration-300 ease-[var(--ease-out)]"
            style={{ transform: `translateX(${lensIndex * 100}%)` }}
          />
        </li>
        {TABS.map(({ id, to, label, Icon }) => (
          <li key={id} className="min-w-0 flex-1">
            <Link
              to={to}
              aria-current={current === id ? "page" : undefined}
              className="glass-press group relative flex h-full min-h-11 min-w-0 flex-col items-center justify-center gap-1 px-0.5"
            >
              <TabInner active={current === id} label={label} Icon={Icon} />
            </Link>
          </li>
        ))}
        <li className="min-w-0 flex-1">
          <Dialog.Root open={moreOpen} onOpenChange={setMoreOpen}>
            <Dialog.Trigger asChild>
              <button type="button" aria-label="More" className="glass-press group relative flex h-full min-h-11 w-full min-w-0 flex-col items-center justify-center gap-1 px-0.5">
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
                            className="glass-subtle glass-press flex h-full min-h-14 min-w-0 items-start gap-2.5 rounded-md border border-border bg-surface-2/60 p-3 transition-colors hover:border-border-strong hover:bg-surface-2"
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
                  <button type="button" onClick={toggle} className={buttonClass("secondary", "md")}>
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
                      className={buttonClass("secondary", "md")}
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
