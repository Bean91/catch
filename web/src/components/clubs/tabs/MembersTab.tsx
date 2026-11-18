import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Card } from "../../ui/Card";
import { EmptyState, ErrorState } from "../../ui/EmptyState";
import { blockClubMember, fetchClubMembers, setClubRole } from "../../../lib/api";
import type { Club, ClubMember, ClubRole } from "../../../lib/types";
import { PrivacyBadge } from "../../coaching/PrivacyBadge";
import { ErrorLine, ROLE_LABEL, RoleBadge, btn, refreshClub } from "../ClubBits";
import { ReasonSheet, ReportSheet } from "../ClubSheets";
import { removeClubMember } from "../../../lib/api";

export function MembersTab({ club }: { club: Club }) {
  const qc = useQueryClient();
  const caps = club.capabilities ?? {};
  const members = useQuery({ queryKey: ["club-members", club.club_id], queryFn: () => fetchClubMembers(club.club_id), retry: false });
  const [error, setError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<ClubMember | null>(null);
  const [reporting, setReporting] = useState<ClubMember | null>(null);
  const role = useMutation({ mutationFn: (v: { ref: string; role: ClubRole }) => setClubRole(club.club_id, v.ref, v.role), onSuccess: () => { setError(null); refreshClub(qc, club.club_id); }, onError: (e: Error) => setError(e.message) });
  const block = useMutation({ mutationFn: (v: { ref: string; blocked: boolean }) => blockClubMember(club.club_id, v.ref, v.blocked), onSuccess: () => refreshClub(qc, club.club_id), onError: (e: Error) => setError(e.message) });
  // A role menu offers what the server would allow; the server still decides.
  const roleChoices = (m: ClubMember): ClubRole[] => (caps.set_roles && m.can_manage ? (["admin", "coach", "athlete"] as ClubRole[]).filter((r) => r !== m.role && (club.my_role === "owner" || r !== "admin") && !(club.audience === "junior" && m.role === "athlete")) : []);
  return (
    <Card title={`Members${members.data ? ` · ${members.data.count}` : ""}`} action={<PrivacyBadge visibility="club" />}>
      {members.isLoading && <p className="text-sm text-text-tertiary">Loading…</p>}
      {members.isError && <ErrorState message="Couldn't load members." onRetry={() => members.refetch()} />}
      {members.data && members.data.members.length === 0 && <EmptyState message="No members yet." />}
      <ul className="flex flex-col divide-y divide-border" data-testid="club-members">
        {(members.data?.members ?? []).map((m) => (
          <li key={m.member_ref} data-testid="member-row" className="flex flex-col gap-2 py-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="flex min-w-0 items-center gap-2">
                <span className="truncate text-sm font-medium text-text-primary">{m.handle}{m.is_me ? " (you)" : ""}</span>
                <RoleBadge role={m.role} />
                {m.guardian_consent !== undefined && <span className="text-xs text-text-tertiary">{m.guardian_consent ? "guardian agreed" : "no guardian note"}</span>}
              </span>
              {!m.is_me && (
                <span className="flex flex-wrap gap-2">
                  <button type="button" className={`${btn} min-h-11 px-3`} onClick={() => block.mutate({ ref: m.member_ref, blocked: !m.blocked })} data-testid="member-block">{m.blocked ? "Unblock" : "Block"}</button>
                  <button type="button" className={`${btn} px-3`} onClick={() => setReporting(m)} data-testid="member-report">Report</button>
                </span>
              )}
            </div>
            {(roleChoices(m).length > 0 || (caps.remove_member && m.can_manage)) && (
              <div className="flex flex-wrap gap-2">
                {roleChoices(m).map((r) => (
                  <button key={r} type="button" className={`${btn} px-3`} onClick={() => role.mutate({ ref: m.member_ref, role: r })} data-testid={`member-make-${r}`}>Make {ROLE_LABEL[r].toLowerCase()}</button>
                ))}
                {caps.remove_member && m.can_manage && <button type="button" className={`${btn} px-3 text-band-red-text`} onClick={() => setRemoving(m)} data-testid="member-remove">Remove</button>}
              </div>
            )}
          </li>
        ))}
      </ul>
      <div className="mt-3"><ErrorLine message={error} /></div>
      <p className="mt-3 text-xs text-text-tertiary">Members are shown by the handle they chose. Blocking only changes what you see; reporting goes to a platform moderator, not to this club's staff.</p>
      {removing && (
        <ReasonSheet open onOpenChange={(o) => !o && setRemoving(null)} testId="remove-sheet" title={`Remove ${removing.handle}`} description="They lose access now and can't rejoin. Your reason is written to the club's audit log." label="Reason (required)" submitLabel="Remove member" danger
          onSubmit={(reason) => removeClubMember(club.club_id, removing.member_ref, reason)} onDone={() => refreshClub(qc, club.club_id)} />
      )}
      {reporting && <ReportSheet open onOpenChange={(o) => !o && setReporting(null)} clubId={club.club_id} targetType="member" targetId={reporting.member_ref} subject={reporting.handle} />}
    </Card>
  );
}
