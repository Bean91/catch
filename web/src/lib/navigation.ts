import type { ComponentType } from "react";
import {
  BodyIcon,
  CalendarIcon,
  ClubsIcon,
  CoachIcon,
  DuplicatesIcon,
  FeedbackIcon,
  GymIcon,
  LeaderboardsIcon,
  LibraryIcon,
  MemoryIcon,
  NutritionIcon,
  ReadinessIcon,
  RoutesIcon,
  SettingsIcon,
  SparkIcon,
  TestsIcon,
  TodayIcon,
  TrendsIcon,
  WorkoutsIcon,
  LabIcon,
  GoalsIcon,
} from "../components/shell/icons";
import { isMock } from "./api";
import { isPublic } from "./deployment";

/**
 * The app's information architecture, in one place (session 35). The desktop sidebar, the phone tab bar, the More sheet and the
 * Train hub all read from here, so a destination can't be reachable from one and missing from another.
 */

export type TabId = "today" | "plan" | "train" | "coach" | "more";
export type GroupId = "overview" | "training" | "health" | "coaching" | "community" | "account";

export type NavItem = {
  to: string;
  label: string;
  Icon: ComponentType<{ className?: string }>;
  group: GroupId;
  /** One line for the More sheet and the Train hub. */
  blurb?: string;
  /** Only on the public build (and the mock): leaderboards and clubs. */
  publicOnly?: boolean;
  /** Shown in the desktop sidebar; the rest are reached from their section's pages and the More sheet. */
  sidebar?: boolean;
};

export const GROUP_LABEL: Record<GroupId, string> = {
  overview: "Overview",
  training: "Training",
  health: "Health",
  coaching: "Coaching",
  community: "Community",
  account: "Account",
};

const ALL: NavItem[] = [
  { to: "/", label: "Today", Icon: TodayIcon, group: "overview", sidebar: true },
  { to: "/calendar", label: "Calendar", Icon: CalendarIcon, group: "overview", sidebar: true, blurb: "Plans, events and what you did" },
  { to: "/trends", label: "Trends", Icon: TrendsIcon, group: "overview", sidebar: true, blurb: "Recovery, load and performance over time" },
  { to: "/trends/intelligence", label: "Training intelligence", Icon: SparkIcon, group: "overview", blurb: "Profile, progression and insights" },
  { to: "/workouts", label: "Workouts", Icon: WorkoutsIcon, group: "training", sidebar: true, blurb: "Every session from every source" },
  { to: "/gym", label: "Gym", Icon: GymIcon, group: "training", sidebar: true, blurb: "Log sets — works offline" },
  { to: "/tests", label: "Tests", Icon: TestsIcon, group: "training", sidebar: true, blurb: "Erg tests, pieces and PBs" },
  { to: "/lab", label: "Performance lab", Icon: LabIcon, group: "training", sidebar: true, blurb: "Records, progression, like-for-like" },
  { to: "/goals", label: "Goals", Icon: GoalsIcon, group: "training", sidebar: true, blurb: "Targets with dates and progress" },
  { to: "/routes", label: "Routes", Icon: RoutesIcon, group: "training", sidebar: true, blurb: "On-water courses and GPS history" },
  { to: "/library", label: "Library", Icon: LibraryIcon, group: "training", sidebar: true, blurb: "Reusable workout templates" },
  { to: "/workouts/duplicates", label: "Duplicates", Icon: DuplicatesIcon, group: "training", blurb: "Review possible double recordings" },
  { to: "/body", label: "Body", Icon: BodyIcon, group: "health", sidebar: true, blurb: "Weight, composition and W/kg" },
  { to: "/nutrition", label: "Nutrition", Icon: NutritionIcon, group: "health", sidebar: true, blurb: "Meals, macros and fuelling" },
  { to: "/gym/readiness", label: "Muscle readiness", Icon: ReadinessIcon, group: "health", blurb: "Recent muscular load by area" },
  { to: "/coach", label: "Coach", Icon: CoachIcon, group: "coaching", sidebar: true },
  { to: "/feedback", label: "Feedback", Icon: FeedbackIcon, group: "coaching", sidebar: true, blurb: "Coach feedback and technique notes" },
  { to: "/settings/memory", label: "Coach memory", Icon: MemoryIcon, group: "coaching", blurb: "Events, goals and facts the coach keeps" },
  { to: "/clubs", label: "Clubs", Icon: ClubsIcon, group: "community", sidebar: true, publicOnly: true, blurb: "Your clubs, sessions and challenges" },
  { to: "/leaderboards", label: "Leaderboards", Icon: LeaderboardsIcon, group: "community", sidebar: true, publicOnly: true, blurb: "Verified results, ranked" },
  { to: "/settings", label: "Settings", Icon: SettingsIcon, group: "account", blurb: "Sources, zones, privacy and more" },
];

const showPublic = isPublic || isMock;

export const NAV_ITEMS: NavItem[] = ALL.filter((i) => !i.publicOnly || showPublic);
export const SETTINGS_ITEM = NAV_ITEMS.find((i) => i.to === "/settings")!;

/** Sidebar groups, in order; Settings is pinned to the sidebar's foot instead. */
export function sidebarGroups(): { id: GroupId; items: NavItem[] }[] {
  const order: GroupId[] = ["overview", "training", "health", "coaching", "community"];
  return order
    .map((id) => ({ id, items: NAV_ITEMS.filter((i) => i.group === id && i.sidebar) }))
    .filter((g) => g.items.length > 0);
}

/** The More sheet: every destination that isn't one of the four tabs, grouped. */
export function moreGroups(): { id: GroupId; items: NavItem[] }[] {
  const inTabs = new Set(["/", "/calendar", "/coach"]);
  const order: GroupId[] = ["overview", "health", "coaching", "community", "account"];
  return order
    .map((id) => ({ id, items: NAV_ITEMS.filter((i) => i.group === id && !inTabs.has(i.to)) }))
    .filter((g) => g.items.length > 0);
}

/** The Train hub's tiles. */
export const TRAIN_ITEMS: NavItem[] = NAV_ITEMS.filter((i) => i.group === "training");

const TRAIN_PREFIXES = ["/train", "/workouts", "/gym", "/tests", "/routes", "/library", "/lab", "/goals"];

function under(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

/** Exactly one tab is active for every route; anything not owned by the first four belongs to More. */
export function tabFor(pathname: string): TabId {
  if (pathname === "/" || pathname === "/checkin") return "today";
  if (under(pathname, "/calendar")) return "plan";
  if (pathname === "/gym/readiness") return "more";
  if (TRAIN_PREFIXES.some((p) => under(pathname, p))) return "train";
  if (under(pathname, "/coach") || under(pathname, "/feedback")) return "coach";
  return "more";
}

/** The sidebar entry that should read as current: the longest matching destination. */
export function activeSidebarPath(pathname: string, items: NavItem[]): string | null {
  let best: string | null = null;
  for (const i of items) {
    if (i.to === "/" ? pathname === "/" || pathname === "/checkin" : under(pathname, i.to)) {
      if (!best || i.to.length > best.length) best = i.to;
    }
  }
  return best;
}
