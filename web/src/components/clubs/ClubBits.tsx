import * as Dialog from "@radix-ui/react-dialog";
import type { QueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { Club, ClubRole } from "../../lib/types";
import { PrivacyBadge } from "../coaching/PrivacyBadge";

export const inputCls = "min-h-11 w-full rounded-md border border-border bg-surface-2 px-3 text-sm text-text-primary";
export const btn = "min-h-11 rounded-md border border-border px-4 text-sm font-medium text-text-primary transition-colors hover:border-accent disabled:cursor-not-allowed disabled:opacity-50";
export const btnPrimary = "min-h-11 rounded-md bg-accent px-4 text-sm font-semibold text-surface transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50";
export const btnDanger = "min-h-11 rounded-md border border-band-red/40 px-4 text-sm font-medium text-band-red-text transition-colors hover:border-band-red disabled:cursor-not-allowed disabled:opacity-50";

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

/** The bottom sheet every club form uses: z-30 so it clears the bottom nav, a bottom sheet on a phone and centred from `sm:`, no autofocus. */
export function Sheet({ open, onOpenChange, title, description, testId, children }: SheetProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-30 bg-black/50" />
        <Dialog.Content
          data-testid={testId}
          onOpenAutoFocus={(e) => e.preventDefault()}
          className="fixed inset-x-0 bottom-0 z-30 max-h-[90vh] overflow-y-auto rounded-t-2xl border-t border-border bg-surface p-5 shadow-xl focus:outline-none sm:inset-x-auto sm:left-1/2 sm:top-1/2 sm:bottom-auto sm:w-[min(92vw,520px)] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-lg sm:border"
        >
          <Dialog.Title className="text-base font-semibold text-text-primary">{title}</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-text-secondary">{description}</Dialog.Description>
          <div className="mt-4 flex flex-col gap-3">{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** Every club query is keyed ["club-…", clubId, …] (or ["clubs-mine"]); after any change, refetch the lot for that club. Explicit key prefixes, not a predicate. */
const CLUB_KEYS = ["club-detail", "club-members", "club-posts", "club-calendar", "club-challenges", "club-challenge", "club-board", "club-summary", "club-requests", "club-invites", "club-audit", "club-workouts"];

export function refreshClub(qc: QueryClient, clubId?: string) {
  qc.invalidateQueries({ queryKey: ["clubs-mine"] });
  qc.invalidateQueries({ queryKey: ["clubs-discover"] });
  for (const key of CLUB_KEYS) qc.invalidateQueries({ queryKey: clubId ? [key, clubId] : [key] });
}
