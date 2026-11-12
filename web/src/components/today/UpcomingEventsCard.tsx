import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Card } from "../ui/Card";
import { fetchUpcomingEvents } from "../../lib/api";
import { formatShortDate } from "../../lib/format";
import { eventTypeLabel } from "../calendar/labels";

export function UpcomingEventsCard() {
  const { data } = useQuery({ queryKey: ["upcoming-events"], queryFn: () => fetchUpcomingEvents(3) });
  const events = data?.events ?? [];
  if (events.length === 0) return null;
  return (
    <Card title="Coming up" action={<Link to="/calendar" className="text-sm text-text-secondary underline">Calendar</Link>}>
      <ul className="flex flex-col" data-testid="upcoming-events">
        {events.map((e) => (
          <li key={e.id}>
            <Link to={`/calendar/events/${e.id}`} className="flex min-h-11 items-center justify-between gap-3 rounded-md py-1 text-sm">
              <span className="min-w-0">
                <span className="block truncate font-medium text-text-primary">{e.name}</span>
                <span className="block truncate text-xs text-text-tertiary">
                  {eventTypeLabel(e.type)}
                  {e.priority ? ` · ${e.priority}` : ""} · {formatShortDate(e.date)}
                </span>
              </span>
              <span className="shrink-0 text-right">
                <span className="font-mono-nums text-lg text-text-primary">{e.days_to_go}</span>
                <span className="block text-xs text-text-tertiary">{e.days_to_go === 1 ? "day" : "days"}</span>
                {e.taper && <span className="text-xs text-accent">Taper</span>}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}
