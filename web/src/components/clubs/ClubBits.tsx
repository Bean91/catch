import type { QueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { Club, ClubRole } from "../../lib/types";
import { PrivacyBadge } from "../coaching/PrivacyBadge";
import { buttonClass } from "../ui/Button";
import { controlClass } from "../ui/Field";
import { Sheet as UiSheet } from "../ui/Sheet";

export const inputCls = controlClass;
export const btn = buttonClass("secondary");
export const btnPrimary = buttonClass("primary");
export const btnDanger = buttonClass("danger");

export const ROLE_LABEL: Record<ClubRole, string> = { owner: "Owner", admin: "Admin", coach: "Coach", athlete: "Athlete" };

export function RoleBadge({ role }: { role: ClubRole }) {
  return (
    <span data-testid="role-badge" data-role={role} className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-xs font-medium text-text-secondary">
      {ROLE_LABEL[role]}
    </span>
  );
}

/** What a club is, in one glance: who can see its insides, and who it is for. Never colour alone. */
export function ClubScope({ club }: { club: Pick<Club, "visibility" | "audience"> }) {
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <PrivacyBadge visibility={club.visibility === "public" ? "public" : "club"} label={club.visibility === "public" ? "Public club" : "Private club"} />
      {club.audience === "junior" && (
        <span data-testid="junior-badge" className="inline-flex items-center rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 text-xs font-medium text-accent">
          Junior club · under 19
        </span>
      )}
    </span>
  );
}

export function ErrorLine({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p role="alert" className="rounded-md border border-band-red/30 bg-band-red/10 px-3 py-2 text-sm text-band-red-text">
      {message}
    </p>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="flex flex-col gap-1 text-sm text-text-secondary">
      <span className="font-medium text-text-primary">{label}</span>
      {children}
      {hint && <span className="text-xs text-text-tertiary">{hint}</span>}
    </label>
  );
}

type SheetProps = { open: boolean; onOpenChange: (open: boolean) => void; title: string; description: string; testId: string; children: ReactNode };

/** The club forms' sheet is the app-wide one (components/ui/Sheet). */
export function Sheet(props: SheetProps) {
  return <UiSheet {...props} />;
}

/** Every club query is keyed ["club-…", clubId, …] (or ["clubs-mine"]); after any change, refetch the lot for that club. Explicit key prefixes, not a predicate. */
const CLUB_KEYS = ["club-detail", "club-members", "club-posts", "club-calendar", "club-challenges", "club-challenge", "club-board", "club-summary", "club-requests", "club-invites", "club-audit", "club-workouts"];

export function refreshClub(qc: QueryClient, clubId?: string) {
  qc.invalidateQueries({ queryKey: ["clubs-mine"] });
  qc.invalidateQueries({ queryKey: ["clubs-discover"] });
  for (const key of CLUB_KEYS) qc.invalidateQueries({ queryKey: clubId ? [key, clubId] : [key] });
}
