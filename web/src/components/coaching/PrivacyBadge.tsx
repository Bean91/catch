import { GlobeIcon, LockIcon, ShareIcon } from "../shell/icons";

type Props = {
  // "private" = only the author; "shared" = also visible to the coach. Technique notes call the
  // shared state "coach" in the API; both mean the same thing here.
  // Session 27: "club" = visible to this club's members only; "public" = visible to every signed-in user.
  visibility: "private" | "shared" | "coach" | "club" | "public";
  // Text override for entries someone else wrote ("Shared with you"). The glyph stays the
  // same, so colour is never the only signal.
  label?: string;
};

const COPY = {
  private: { text: "Private — only you", title: "Only you can see this. It is never sent to a coach." },
  shared: { text: "Shared with coach", title: "A linked coach can see this." },
  club: { text: "Club-only", title: "Only members of this club can see this." },
  public: { text: "Public", title: "Every signed-in Catch user can see this." },
} as const;

export function PrivacyBadge({ visibility, label }: Props) {
  const kind = visibility === "coach" ? "shared" : visibility;
  const copy = COPY[kind];
  // Unchanged for the original states ("private" | "shared"); the club states add their own value so a test can tell the three scopes apart.
  const tone = kind === "private" ? "border-border text-text-secondary" : kind === "public" ? "border-border bg-surface-2 text-text-primary" : "border-accent/30 bg-accent/10 text-accent";
  const Glyph = kind === "private" ? LockIcon : kind === "public" ? GlobeIcon : ShareIcon;
  return (
    <span
      data-testid="privacy-badge"
      data-visibility={kind}
      title={copy.title}
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${tone}`}
    >
      <Glyph className="h-3.5 w-3.5" />
      {label ?? copy.text}
    </span>
  );
}
