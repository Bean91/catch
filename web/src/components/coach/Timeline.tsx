import { Link } from "react-router-dom";
import { splitRefs } from "../../lib/coachRefs";
import type { TimelineEntry } from "../../lib/timeline";
import { ToolCallChip } from "./ToolCallChip";

const PROVIDER_LABELS: Record<string, string> = { anthropic: "Claude", ollama: "Ollama" };

function Attribution({ provider, model }: { provider?: string | null; model?: string | null }) {
  if (!provider) return null;
  const label = PROVIDER_LABELS[provider] ?? provider;
  return (
    <p className="mt-1 text-xs text-text-tertiary">
      — {label}
      {model ? ` (${model})` : ""}
    </p>
  );
}

function TextBlock({
  role,
  text,
  provider,
  model,
}: {
  role: "user" | "assistant";
  text: string;
  provider?: string | null;
  model?: string | null;
}) {
  if (role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-accent px-3.5 py-2.5 text-sm text-accent-contrast shadow-subtle sm:max-w-[75%]">
          <p className="whitespace-pre-wrap">{text}</p>
        </div>
      </div>
    );
  }
  return (
    <div className="flex max-w-full gap-2.5">
      <CoachAvatar />
      <div className="min-w-0 max-w-[92%] rounded-2xl rounded-tl-md border border-border bg-surface-2/70 px-3.5 py-2.5 text-sm leading-relaxed text-text-primary">
        <p className="whitespace-pre-wrap">
          <LinkedText text={text} />
        </p>
        <Attribution provider={provider} model={model} />
      </div>
    </div>
  );
}

export function Timeline({ entries, streamingText }: { entries: TimelineEntry[]; streamingText?: string }) {
  return (
    <div className="flex flex-col gap-3.5">
      {entries.map((entry) =>
        entry.kind === "text" ? (
          <TextBlock key={entry.key} role={entry.role} text={entry.text} provider={entry.provider} model={entry.model} />
        ) : (
          <ToolCallChip key={entry.key} label={entry.label} output={entry.output} isError={entry.isError} pending={entry.pending} />
        ),
      )}
      {streamingText != null && (
        <div className="flex max-w-full gap-2.5">
          <CoachAvatar />
          <p className="min-w-0 max-w-[92%] whitespace-pre-wrap rounded-2xl rounded-tl-md border border-border bg-surface-2/70 px-3.5 py-2.5 text-sm leading-relaxed text-text-primary">
            {streamingText}
            <span aria-hidden className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-text-tertiary align-middle" />
          </p>
        </div>
      )}
    </div>
  );
}

function CoachAvatar() {
  return (
    <span aria-hidden className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[linear-gradient(135deg,var(--accent-strong),var(--metric-pace))] text-[11px] font-bold text-accent-contrast">
      C
    </span>
  );
}

/** Session 36: the in-app paths the coach cites ("/workouts/123") become links — only the allow-listed shapes in lib/coachRefs. */
function LinkedText({ text }: { text: string }) {
  return (
    <>
      {splitRefs(text).map((p, i) =>
        p.to ? (
          <Link key={i} to={p.to} className="text-accent underline" data-testid="coach-ref">
            {p.text}
          </Link>
        ) : (
          <span key={i}>{p.text}</span>
        ),
      )}
    </>
  );
}
