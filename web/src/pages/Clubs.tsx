import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Card } from "../components/ui/Card";
import { EmptyState, ErrorState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Skeleton";
import { ClubScope, ErrorLine, RoleBadge, btn, btnPrimary, inputCls, refreshClub } from "../components/clubs/ClubBits";
import { CreateClubSheet, ProfileSheet } from "../components/clubs/ClubSheets";
import { fetchDiscoverClubs, fetchMyClubs, withdrawClubRequest } from "../lib/api";

export function ClubsPage() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const mine = useQuery({ queryKey: ["clubs-mine"], queryFn: fetchMyClubs, retry: false });
  const [q, setQ] = useState("");
  const discover = useQuery({ queryKey: ["clubs-discover", q], queryFn: () => fetchDiscoverClubs(q), retry: false, enabled: mine.isSuccess });
  const [profiling, setProfiling] = useState(false);
  const [creating, setCreating] = useState(false);
  const [link, setLink] = useState("");
  const [error, setError] = useState<string | null>(null);
  const withdraw = useMutation({ mutationFn: (id: number) => withdrawClubRequest(id), onSuccess: () => refreshClub(qc), onError: (e: Error) => setError(e.message) });

  if (mine.isLoading) return <div className="flex flex-col gap-4"><Skeleton className="h-16" /><Skeleton className="h-40" /></div>;
  if (mine.isError || !mine.data) {
    return <p data-testid="clubs-unavailable" className="text-sm text-text-secondary">Clubs are only available on the public Catch deployment.</p>;
  }
  const { profile, clubs, requests } = mine.data;
  const waiting = requests.filter((r) => r.status === "pending");
  const decided = requests.filter((r) => r.status === "rejected").slice(0, 3);
  const go = () => {
    const token = link.includes("#") ? link.split("#").pop() ?? "" : link.trim();
    nav(`/clubs/join#${encodeURIComponent(token)}`);
  };
  return (
    <div className="flex flex-col gap-4" data-testid="clubs-page">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold text-text-primary">Clubs</h1>
        {profile.exists && <button type="button" className={btnPrimary} onClick={() => setCreating(true)} data-testid="clubs-start">Start a club</button>}
      </header>

      <Card title="Your club profile">
        {profile.exists ? (
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <span className="text-text-secondary">Clubs see you as <strong data-testid="profile-handle-shown" className="text-text-primary">{profile.handle}</strong> · {profile.age_class === "youth" ? `under ${profile.age_band?.slice(1)}` : "adult"}. Never your real name or email.</span>
            <button type="button" className={btn} onClick={() => setProfiling(true)} data-testid="clubs-edit-profile">Edit</button>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            <p className="text-sm text-text-secondary">Choose a handle and an age group before you join or start a club. Clubs never show your real name, email, or any health data.</p>
            <div><button type="button" className={btnPrimary} onClick={() => setProfiling(true)} data-testid="clubs-profile-setup">Set up your profile</button></div>
          </div>
        )}
      </Card>

      <Card title="Your clubs">
        {clubs.length === 0 ? <EmptyState message="You're not in a club yet." /> : (
          <ul className="flex flex-col gap-3" data-testid="clubs-mine">
            {clubs.map((c) => (
              <li key={c.club_id}>
                <Link to={`/clubs/${c.club_id}`} data-testid="club-link" className="flex flex-col gap-2 rounded-md border border-border p-3 transition-colors hover:border-accent/40">
                  <span className="flex flex-wrap items-center justify-between gap-2">
                    <span className="min-w-0 wrap-anywhere text-sm font-semibold text-text-primary">{c.name}</span>
                    {c.my_role && <RoleBadge role={c.my_role} />}
                  </span>
                  <ClubScope club={c} />
                  <span className="text-xs text-text-tertiary">
                    {c.member_count} member{c.member_count === 1 ? "" : "s"}
                    {c.pending && c.pending.requests + c.pending.posts > 0 ? ` · ${c.pending.requests + c.pending.posts} waiting for you` : ""}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {(waiting.length > 0 || decided.length > 0) && (
        <Card title="Your requests">
          <ul className="flex flex-col gap-2" data-testid="clubs-requests">
            {waiting.map((r) => (
              <li key={r.request_id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span className="text-text-primary">{r.club_name} <span className="text-xs text-text-tertiary">· waiting for a decision</span></span>
                <button type="button" className={`${btn} px-3`} onClick={() => withdraw.mutate(r.request_id)} data-testid="request-withdraw">Withdraw</button>
              </li>
            ))}
            {decided.map((r) => <li key={r.request_id} className="text-sm text-text-secondary">{r.club_name} — not approved{r.decision_reason ? `: ${r.decision_reason}` : ""}</li>)}
          </ul>
        </Card>
      )}

      <Card title="Join with an invite link">
        <div className="flex flex-col gap-2 sm:flex-row">
          <input value={link} onChange={(e) => setLink(e.target.value)} placeholder="Paste an invite link" className={inputCls} aria-label="Invite link" data-testid="clubs-join-input" />
          <button type="button" className={btn} onClick={go} disabled={!link.trim()} data-testid="clubs-join-go">Continue</button>
        </div>
        <p className="mt-2 text-xs text-text-tertiary">Private and junior clubs are joined only by invitation, and aren't listed anywhere.</p>
      </Card>

      <Card title="Discover public clubs">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by name" className={inputCls} aria-label="Search clubs" data-testid="clubs-discover-search" />
        {discover.isError && <div className="mt-3"><ErrorState message="Couldn't load clubs." onRetry={() => discover.refetch()} /></div>}
        {discover.data && discover.data.clubs.length === 0 && <div className="mt-3"><EmptyState message="No public clubs match." /></div>}
        <ul className="mt-3 flex flex-col gap-3" data-testid="clubs-discover">
          {(discover.data?.clubs ?? []).map((c) => (
            <li key={c.club_id}>
              <Link to={`/clubs/${c.club_id}`} data-testid="discover-row" className="flex flex-col gap-1 rounded-md border border-border p-3 transition-colors hover:border-accent/40">
                <span className="min-w-0 wrap-anywhere text-sm font-semibold text-text-primary">{c.name}</span>
                {c.description && <span className="text-sm text-text-secondary">{c.description}</span>}
                <span className="text-xs text-text-tertiary">{c.location ? `${c.location} · ` : ""}{c.member_count} members · {c.join_policy === "open" ? "open to join" : "by request"}</span>
              </Link>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-text-tertiary">Only public adult clubs are listed, with a count — never a member list.</p>
      </Card>

      <ErrorLine message={error} />
      <ProfileSheet open={profiling} onOpenChange={setProfiling} profile={profile} />
      <CreateClubSheet open={creating} onOpenChange={setCreating} onCreated={(c) => nav(`/clubs/${c.club_id}`)} />
    </div>
  );
}
