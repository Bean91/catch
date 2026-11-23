import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BackLink } from "../components/ui/PageHeader";
import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { Card } from "../components/ui/Card";
import { ErrorState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Skeleton";
import { PrivacyBadge } from "../components/coaching/PrivacyBadge";
import { ClubScope, ErrorLine, RoleBadge, btnPrimary, inputCls, refreshClub } from "../components/clubs/ClubBits";
import { ProfileSheet } from "../components/clubs/ClubSheets";
import { BoardTab } from "../components/clubs/tabs/BoardTab";
import { CalendarTab } from "../components/clubs/tabs/CalendarTab";
import { ChallengesTab } from "../components/clubs/tabs/ChallengesTab";
import { ManageTab } from "../components/clubs/tabs/ManageTab";
import { MembersTab } from "../components/clubs/tabs/MembersTab";
import { NewsTab } from "../components/clubs/tabs/NewsTab";
import { OverviewTab } from "../components/clubs/tabs/OverviewTab";
import { fetchClub, fetchClubLogoUrl, fetchMyClubs, joinClub } from "../lib/api";
import type { Club } from "../lib/types";

const TABS = [["overview", "Overview"], ["news", "News"], ["calendar", "Calendar"], ["challenges", "Challenges"], ["board", "Board"], ["members", "Members"], ["manage", "Manage"]] as const;

function Logo({ club }: { club: Club }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let revoke: string | null = null;
    let live = true;
    if (club.has_logo) fetchClubLogoUrl(club.club_id).then((u) => { if (live) { setUrl(u); revoke = u; } else if (u) URL.revokeObjectURL(u); });
    return () => { live = false; if (revoke) URL.revokeObjectURL(revoke); };
  }, [club.club_id, club.has_logo]);
  if (!url) return null;
  return <img src={url} alt={`${club.name} logo`} data-testid="club-logo" className="h-14 w-14 shrink-0 rounded-md border border-border object-cover" />;
}

/** A public club seen by someone who isn't in it: what it is and how to join. The insides stay members-only. */
function PublicView({ club }: { club: Club }) {
  const qc = useQueryClient();
  const mine = useQuery({ queryKey: ["clubs-mine"], queryFn: fetchMyClubs, retry: false });
  const [accept, setAccept] = useState(false);
  const [message, setMessage] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [profiling, setProfiling] = useState(false);
  const join = useMutation({
    mutationFn: () => joinClub({ club_id: club.club_id, message: message || undefined, accept_rules: accept }),
    onSuccess: (r) => { setError(null); refreshClub(qc, club.club_id); if (r.status === "requested") setNote(`Request sent — ${r.needs ?? "the club will decide"}.`); },
    onError: (e: Error) => setError(e.message),
  });
  const needsProfile = mine.data && !mine.data.profile.exists;
  return (
    <div className="flex flex-col gap-4" data-testid="club-public-view">
      {club.description && <Card title="About"><p className="whitespace-pre-line text-sm text-text-primary">{club.description}</p>{club.location && <p className="mt-2 text-xs text-text-tertiary">{club.location}</p>}</Card>}
      {club.rules && <Card title="Club rules"><p className="whitespace-pre-line text-sm text-text-primary">{club.rules}</p></Card>}
      <Card title="Join" action={<PrivacyBadge visibility="club" label="Members-only inside" />}>
        <p className="text-sm text-text-secondary">You can see what this club is. Its members, posts, calendar and results are for members only.</p>
        {note ? (
          <p role="status" data-testid="join-note" className="mt-3 rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-text-secondary">{note}</p>
        ) : needsProfile ? (
          <div className="mt-3"><button type="button" className={btnPrimary} onClick={() => setProfiling(true)} data-testid="join-needs-profile">Set up your club profile to join</button></div>
        ) : (
          <div className="mt-3 flex flex-col gap-3">
            {club.join_policy === "request" && <textarea value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Say hello (optional)" rows={2} maxLength={300} className={`${inputCls} py-2`} data-testid="join-message" />}
            {club.rules && <label className="flex items-start gap-2 text-sm text-text-secondary"><input type="checkbox" checked={accept} onChange={(e) => setAccept(e.target.checked)} className="mt-1 h-4 w-4" data-testid="join-accept-rules" />I've read the club rules and agree to them.</label>}
            <ErrorLine message={error} />
            <div><button type="button" className={btnPrimary} onClick={() => join.mutate()} disabled={join.isPending || (!!club.rules && !accept)} data-testid="join-go">{club.join_policy === "open" ? "Join this club" : "Request to join"}</button></div>
          </div>
        )}
      </Card>
      {mine.data && <ProfileSheet open={profiling} onOpenChange={setProfiling} profile={mine.data.profile} />}
    </div>
  );
}

export function ClubPage() {
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const club = useQuery({ queryKey: ["club-detail", id], queryFn: () => fetchClub(id), retry: false });
  const tab = params.get("tab") ?? "overview";

  if (club.isLoading) return <div className="flex flex-col gap-4"><Skeleton className="h-16" /><Skeleton className="h-40" /></div>;
  if (club.isError || !club.data) {
    return (
      <div className="flex flex-col gap-3">
        <BackLink to="/clubs">Clubs</BackLink>
        <ErrorState message="That club isn't available. It may be private, or you may have left it." />
      </div>
    );
  }
  const c = club.data;
  const caps = c.capabilities ?? {};
  const isMember = c.my_role !== null;
  const visible = TABS.filter(([key]) => key !== "manage" || caps.see_requests || caps.see_audit || caps.edit_club);
  const pendingTotal = (c.pending?.requests ?? 0) + (c.pending?.posts ?? 0);

  return (
    <div className="flex flex-col gap-4" data-testid="club-page">
      <BackLink to="/clubs">Clubs</BackLink>
      <header data-testid="club-header" className="flex items-start gap-3">
        <Logo club={c} />
        <div className="flex min-w-0 flex-col gap-2">
          <h1 className="truncate text-2xl font-semibold leading-tight tracking-tight text-text-primary sm:text-[1.75rem]">{c.name}</h1>
          <ClubScope club={c} />
          <p className="text-xs text-text-tertiary">{c.member_count ?? 0} member{c.member_count === 1 ? "" : "s"}{c.my_role ? " · you are " : ""}{c.my_role && <RoleBadge role={c.my_role} />}</p>
        </div>
      </header>
      {c.status === "suspended" && <p role="status" data-testid="club-suspended" className="rounded-md border border-band-red/30 bg-band-red/10 px-3 py-2 text-sm text-band-red-text">A platform moderator has paused this club while they review reports. You can still read it.</p>}
      {c.audience === "junior" && isMember && <p data-testid="junior-note" className="rounded-md border border-border bg-surface-2 px-3 py-2 text-xs text-text-secondary">Junior club: members are under 19 and approved by a coach or the owner; staff are adults. Posts from anyone else wait for a coach's approval, and there are no private messages here.</p>}
      {!isMember ? (
        <PublicView club={c} />
      ) : (
        <>
          <div role="tablist" aria-label="Club sections" className="-mx-4 flex gap-1 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0">
            {visible.map(([key, label]) => (
              <button key={key} type="button" role="tab" aria-selected={tab === key} data-testid={`club-tab-${key}`} onClick={() => setParams({ tab: key }, { replace: true })}
                className={`min-h-11 shrink-0 rounded-md px-3 text-sm transition-colors ${tab === key ? "bg-surface-2 text-accent" : "text-text-tertiary hover:text-text-secondary"}`}>
                {label}{key === "manage" && pendingTotal > 0 ? <span data-testid="manage-badge" className="ml-1 rounded-full bg-accent px-1.5 py-0.5 text-xs text-surface">{pendingTotal}</span> : null}
              </button>
            ))}
          </div>
          {tab === "overview" && <OverviewTab club={c} />}
          {tab === "news" && <NewsTab club={c} />}
          {tab === "calendar" && <CalendarTab club={c} />}
          {tab === "challenges" && <ChallengesTab club={c} />}
          {tab === "board" && <BoardTab club={c} />}
          {tab === "members" && <MembersTab club={c} />}
          {tab === "manage" && <ManageTab club={c} />}
        </>
      )}
    </div>
  );
}
