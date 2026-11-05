// Mirrors catch/coach/chat.py's _tool_label — only needed for persisted history, where the
// stored blocks carry name+input but not the label (labels are a live-stream-only SSE field,
// not part of the provider-neutral block shape CoachMessage.blocks_json stores).
function rangePhrase(args: Record<string, unknown>): string {
  if (args.from || args.to) return ` (${args.from ?? "…"} to ${args.to ?? "now"})`;
  return "";
}

const STATIC_LABELS: Record<string, string> = {
  get_today: "Read today's recovery and strain",
  get_load: "Read current training load",
  predict_2k: "Predict 2k time",
  get_zones: "Read training zones",
  set_goal: "Save goal",
  recall: "Search memory",
};

export function toolLabel(name: string, input: Record<string, unknown>): string {
  if (STATIC_LABELS[name]) return STATIC_LABELS[name];
  switch (name) {
    case "get_wellness":
      return `Read wellness history${rangePhrase(input)}`;
    case "list_workouts":
      return "Read recent workouts";
    case "get_workout":
      return `Read workout #${input.id}`;
    case "get_trends":
      return `Read ${input.metric ?? "a"} trend${rangePhrase(input)}`;
    case "get_body_comp":
      return `Read body-composition history${rangePhrase(input)}`;
    case "add_note":
      return `Save a note for ${input.date}`;
    case "remember":
      return `Remember a ${input.category} fact`;
    case "add_event":
      return `Add event: ${input.name}`;
    case "update_event":
      return `Update event #${input.id}`;
    case "forget":
      return `Forget ${input.ref}`;
    case "rename_activity":
      return `Rename workout #${input.id} to "${input.title}"`;
    case "tag_activity":
      return `Tag workout #${input.id}`;
    case "merge_activities":
      return input.confirm ? "Merge two workouts" : "Preview merging two workouts";
    case "get_nutrition":
      return `Read nutrition history${rangePhrase(input)}`;
    case "log_food":
      return `Log ${input.description ?? input.barcode ?? "a food"}`;
    case "log_strength":
      return input.confirm ? "Log a set" : "Preview a logged set";
    case "get_strength":
      return `Read strength history${rangePhrase(input)}`;
    case "get_muscle_readiness":
      return "Read muscle readiness";
    default:
      return name;
  }
}
