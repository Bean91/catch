import { LockIcon, ShareIcon } from "../shell/icons";

type Props = {
  // "private" = only the author; "shared" = also visible to the coach. Technique notes call the
  // shared state "coach" in the API; both mean the same thing here.
  visibility: "private" | "shared" | "coach";
  // Text override for entries someone else wrote ("Shared with you"). The glyph stays the
  // same, so colour is never the only signal.
  label?: string;
};

export function PrivacyBadge({ visibility, label }: Props) {
  const isPrivate = visibility === "private";
  const text = label ?? (isPrivate ? "Private — only you" : "Shared with coach");
  return (
    <span
      data-testid="privacy-badge"
      data-visibility={isPrivate ? "private" : "shared"}
      title={isPrivate ? "Only you can see this. It is never sent to a coach." : "A linked coach can see this."}
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${
        isPrivate ? "border-border text-text-secondary" : "border-accent/30 bg-accent/10 text-accent"
      }`}
    >
      {isPrivate ? <LockIcon className="h-3.5 w-3.5" /> : <ShareIcon className="h-3.5 w-3.5" />}
      {text}
    </span>
  );
}
