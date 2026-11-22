import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { fetchConnections } from "../lib/api";
import { CONNECT_RESULT_TEXT } from "../lib/connections";
import { ConnectionCard } from "../components/connections/ConnectionCard";
import { Card } from "../components/ui/Card";
import { CardSkeleton } from "../components/ui/Skeleton";
import { healthPlatform } from "../lib/native/health";
import { isNative } from "../lib/native/platform";

export function ConnectionsPage() {
  const query = useQuery({ queryKey: ["connections"], queryFn: fetchConnections });
  const [params] = useSearchParams();
  const provider = params.get("provider");
  const result = CONNECT_RESULT_TEXT[params.get("result") ?? ""];
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

      {isNative() && healthPlatform() && (
        <Card title={healthPlatform() === "apple_health" ? "Apple Health" : "Health Connect"}>
          <p className="text-sm text-text-secondary">
            Optional. Bring workouts, sleep and heart data from your phone into Catch — only the types you choose, only after you confirm a preview.
          </p>
          <Link to="/settings/health" className="mt-3 inline-flex min-h-11 items-center rounded-md border border-border px-4 text-sm font-medium text-text-primary hover:border-accent">
            Set up
          </Link>
        </Card>
      )}

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
