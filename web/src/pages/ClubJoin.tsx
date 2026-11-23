import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BackLink } from "../components/ui/PageHeader";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Card } from "../components/ui/Card";
import { ErrorState } from "../components/ui/EmptyState";
import { ClubScope, ErrorLine, btn, btnPrimary, inputCls, refreshClub } from "../components/clubs/ClubBits";
import { ProfileSheet } from "../components/clubs/ClubSheets";
import { PrivacyBadge } from "../components/coaching/PrivacyBadge";
import { fetchMyClubs, joinClub, previewClubInvite } from "../lib/api";

/** An invite link lands here. The token lives in the URL fragment (`/clubs/join#…`), which a browser never sends to a server or writes to a log. */
export function ClubJoinPage() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const [token, setToken] = useState(() => decodeURIComponent(window.location.hash.replace(/^#/, "")));
  const [pasted, setPasted] = useState("");
  const [accept, setAccept] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [profiling, setProfiling] = useState(false);
  const mine = useQuery({ queryKey: ["clubs-mine"], queryFn: fetchMyClubs, retry: false });
  const preview = useQuery({ queryKey: ["club-invite-preview", token], queryFn: () => previewClubInvite(token), enabled: !!token, retry: false });
  const join = useMutation({
    mutationFn: () => joinClub({ token, message: message || undefined, accept_rules: accept }),
    onSuccess: (r) => {
      setError(null);
      refreshClub(qc);
      window.history.replaceState(null, "", "/clubs/join"); // the token is spent from the address bar as soon as it's used
      if (r.status === "joined") nav(`/clubs/${r.club_id}`);
      else setNote(`Request sent — ${r.needs ?? "the club will decide"}. You'll see it on your Clubs page.`);
    },
    onError: (e: Error) => setError(e.message),
  });

  if (!token) {
    return (
      <div className="flex flex-col gap-4" data-testid="club-join-page">
        <h1 className="text-2xl font-semibold leading-tight tracking-tight text-text-primary sm:text-[1.75rem]">Join with an invite</h1>
        <Card title="Paste your invite link">
          <div className="flex flex-col gap-2 sm:flex-row">
            <input value={pasted} onChange={(e) => setPasted(e.target.value)} placeholder="Invite link or code" className={inputCls} aria-label="Invite link" data-testid="join-paste" />
            <button type="button" className={btnPrimary} disabled={!pasted.trim()} onClick={() => setToken(pasted.includes("#") ? decodeURIComponent(pasted.split("#").pop() ?? "") : pasted.trim())} data-testid="join-paste-go">Continue</button>
          </div>
        </Card>
        <BackLink to="/clubs">Clubs</BackLink>
      </div>
    );
  }
  if (preview.isLoading) return <p className="text-sm text-text-tertiary">Checking the invite…</p>;
  if (preview.isError || !preview.data) {
    return (
      <div className="flex flex-col gap-3" data-testid="club-join-page">
        <ErrorState message="This invite link isn't valid any more. Ask for a new one." />
        <BackLink to="/clubs">Clubs</BackLink>
      </div>
    );
  }
  const p = preview.data;
  const needsProfile = p.needs_profile || (mine.data && !mine.data.profile.exists);
  const blocked = p.cannot_join_because;
  return (
    <div className="flex flex-col gap-4" data-testid="club-join-page">
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold leading-tight tracking-tight text-text-primary sm:text-[1.75rem]">You're invited to {p.name}</h1>
        <ClubScope club={p} />
      </header>
      {p.description && <Card title="About"><p className="text-sm text-text-primary">{p.description}</p></Card>}
      {p.audience === "junior" && (
        <p data-testid="join-junior-note" className="rounded-md border border-accent/30 bg-accent/10 px-3 py-2 text-sm text-text-secondary">
          This is a junior club for under-19s. {p.role === "coach" ? "As an adult coach you'll be approved by the club's owner or an admin." : "A coach will approve your request before you're in. A parent or guardian should know you're joining."}
        </p>
      )}
      {p.rules && <Card title="Club rules" action={<PrivacyBadge visibility="club" />}><p className="whitespace-pre-line text-sm text-text-primary">{p.rules}</p></Card>}
      {p.already_member ? <p role="status" className="text-sm text-text-secondary">You're already in this club.</p> : note ? (
        <p role="status" data-testid="join-note" className="rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-text-secondary">{note}</p>
      ) : blocked ? (
        <p role="alert" data-testid="join-blocked" className="rounded-md border border-band-red/30 bg-band-red/10 px-3 py-2 text-sm text-band-red-text">You can't join this club: {blocked}.</p>
      ) : needsProfile ? (
        <div><button type="button" className={btnPrimary} onClick={() => setProfiling(true)} data-testid="join-needs-profile">Set up your club profile first</button></div>
      ) : (
        <Card title="Join">
          <div className="flex flex-col gap-3">
            {p.will_need_approval && <textarea value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Say hello (optional)" rows={2} maxLength={300} className={`${inputCls} py-2`} data-testid="join-message" />}
            {p.rules && <label className="flex items-start gap-2 text-sm text-text-secondary"><input type="checkbox" checked={accept} onChange={(e) => setAccept(e.target.checked)} className="mt-1 h-4 w-4" data-testid="join-accept-rules" />I've read the club rules and agree to them.</label>}
            <ErrorLine message={error} />
            <div className="flex gap-2">
              <button type="button" className={btnPrimary} onClick={() => join.mutate()} disabled={join.isPending || (!!p.rules && !accept)} data-testid="join-go">{p.will_need_approval ? "Ask to join" : "Join club"}</button>
              <Link to="/clubs" className={`${btn} inline-flex items-center`}>Not now</Link>
            </div>
          </div>
        </Card>
      )}
      {mine.data && <ProfileSheet open={profiling} onOpenChange={setProfiling} profile={mine.data.profile} />}
    </div>
  );
}
