import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { fetchConnections } from "../lib/api";
import { ConnectionCard } from "../components/connections/ConnectionCard";
import { Card } from "../components/ui/Card";
import { CardSkeleton } from "../components/ui/Skeleton";

const RESULT_TEXT: Record<string, string> = {
  connected: "connected.",
  denied: "access wasn't granted, so nothing changed.",
  failed: "couldn't be connected. Try again; if it keeps failing, check that sign-in is set up on this server.",
};

export function ConnectionsPage() {
  const query = useQuery({ queryKey: ["connections"], queryFn: fetchConnections });
  const [params] = useSearchParams();
  const provider = params.get("provider");
  const result = RESULT_TEXT[params.get("result") ?? ""];
  const label = query.data?.connections.find((c) => c.provider === provider)?.label ?? provider;

  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <div>
        <Link to="/settings" className="text-sm font-medium text-accent hover:underline">
          ← Settings
        </Link>
        <h1 className="mt-1 text-lg font-semibold text-text-primary">Connections</h1>
        <p className="mt-1 text-sm text-text-secondary">
          Each source uses your own account. Passwords are never asked for or stored; keys and tokens are stored encrypted on the server and never
          shown again. Disconnecting never deletes what Catch already imported.
        </p>
      </div>

      {provider && result && (
        <p role="status" data-testid="connection-result" className="rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-text-secondary">
          {label} {result}
        </p>
      )}

      {query.isLoading && <CardSkeleton lines={4} />}
      {query.isError && <p className="text-sm text-band-red-text">Couldn't load your connections.</p>}
      {query.data?.connections.map((c) => <ConnectionCard key={c.provider} card={c} />)}

      <Card title="Sync health">
        <p className="text-sm text-text-secondary">
          Catch checks each connected source on its own schedule and backs off when a source fails or asks it to slow down, so one source's trouble never
          holds up the others. For the raw numbers, see{" "}
          <Link to="/settings/status" className="font-medium text-accent hover:underline">
            Status
          </Link>
          .
        </p>
      </Card>
    </div>
  );
}
