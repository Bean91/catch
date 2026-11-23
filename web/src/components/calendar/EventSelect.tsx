import { useQuery } from "@tanstack/react-query";
import { fetchUpcomingEvents } from "../../lib/api";
import { formatShortDate } from "../../lib/format";

/** "Towards which event" — the upcoming events, plus the one already chosen if it has passed. Optional; empty means none. */
export function EventSelect({ value, onChange, className, enabled = true }: { value: number | null; onChange: (id: number | null) => void; className: string; enabled?: boolean }) {
  const q = useQuery({ queryKey: ["upcoming-events", 20], queryFn: () => fetchUpcomingEvents(20), enabled });
  const events = q.data?.events ?? [];
  return (
    <select value={value ?? ""} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)} className={className} data-testid="event-select">
      <option value="">No event</option>
      {value != null && !events.some((e) => e.id === value) && <option value={value}>The event already linked</option>}
      {events.map((e) => (
        <option key={e.id} value={e.id}>
          {e.name} · {formatShortDate(e.date)}
        </option>
      ))}
    </select>
  );
}
