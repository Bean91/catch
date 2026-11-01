import type { CoachMessageRow } from "./types";
import { toolLabel } from "./toolLabels";

export type TimelineEntry =
  | { kind: "text"; key: string; role: "user" | "assistant"; text: string; provider?: string | null; model?: string | null; cost_usd?: number | null }
  | {
      kind: "tool";
      key: string;
      id: string;
      name: string;
      label: string;
      input: Record<string, unknown>;
      output: unknown;
      isError: boolean;
      pending: boolean;
    };

// A stored conversation keeps tool_call and tool_result blocks on two separate message rows
// (the assistant turn that called it, then the user-role turn carrying the result) — this
// flattens both into one entry per tool call so the UI shows one chip, not two disconnected
// fragments across a role boundary the athlete never asked about.
export function buildTimeline(messages: CoachMessageRow[]): TimelineEntry[] {
  const entries: TimelineEntry[] = [];
  const byId = new Map<string, TimelineEntry & { kind: "tool" }>();

  for (const msg of messages) {
    for (const block of msg.blocks) {
      if (block.type === "text") {
        entries.push({
          kind: "text",
          key: `${msg.id}-${entries.length}`,
          role: msg.role,
          text: block.text,
          provider: msg.provider,
          model: msg.model,
          cost_usd: msg.cost_usd,
        });
      } else if (block.type === "tool_call") {
        const entry: TimelineEntry & { kind: "tool" } = {
          kind: "tool",
          key: block.id,
          id: block.id,
          name: block.name,
          label: toolLabel(block.name, block.input),
          input: block.input,
          output: undefined,
          isError: false,
          pending: true,
        };
        entries.push(entry);
        byId.set(block.id, entry);
      } else if (block.type === "tool_result") {
        const entry = byId.get(block.id);
        if (entry) {
          entry.output = block.output;
          entry.isError = block.is_error;
          entry.pending = false;
        }
      }
    }
  }
  return entries;
}
