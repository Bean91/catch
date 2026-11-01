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
        <div className="max-w-[85%] rounded-lg bg-surface-2 px-3.5 py-2.5 text-sm text-text-primary sm:max-w-[75%]">
          <p className="whitespace-pre-wrap">{text}</p>
        </div>
      </div>
    );
  }
  return (
    <div className="max-w-full text-sm text-text-primary">
      <p className="whitespace-pre-wrap">{text}</p>
      <Attribution provider={provider} model={model} />
    </div>
  );
}

export function Timeline({ entries, streamingText }: { entries: TimelineEntry[]; streamingText?: string }) {
  return (
    <div className="flex flex-col gap-3">
      {entries.map((entry) =>
        entry.kind === "text" ? (
          <TextBlock key={entry.key} role={entry.role} text={entry.text} provider={entry.provider} model={entry.model} />
        ) : (
          <ToolCallChip key={entry.key} label={entry.label} output={entry.output} isError={entry.isError} pending={entry.pending} />
        ),
      )}
      {streamingText != null && (
        <div className="max-w-full text-sm text-text-primary">
          <p className="whitespace-pre-wrap">
            {streamingText}
            <span aria-hidden className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-text-tertiary align-middle" />
          </p>
        </div>
      )}
    </div>
  );
}
