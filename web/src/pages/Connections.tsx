import { useQuery } from "@tanstack/react-query";
import { buttonClass } from "../components/ui/Button";
import { ErrorState } from "../components/ui/EmptyState";
import { Notice } from "../components/ui/Notice";
import { PageHeader } from "../components/ui/PageHeader";
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
      <PageHeader
        back={{ to: "/settings", label: "Settings" }}
        eyebrow="Sources and data"
        title="Connections"
        subtitle="Each source uses your own account. Passwords are never asked for or stored; keys and tokens are stored encrypted on the server and never shown again. Disconnecting never deletes what Catch already imported."
      />

      {provider && result && (
        <Notice tone={params.get("result") === "connected" ? "success" : "info"} role="status" testId="connection-result">
          {label} {result}
        </Notice>
      )}

      {query.isLoading && <CardSkeleton lines={4} />}
      {query.isError && <ErrorState message="Couldn't load your connections." onRetry={() => query.refetch()} />}
      <div className="grid gap-4 lg:grid-cols-2 lg:gap-5">{query.data?.connections.map((c) => <ConnectionCard key={c.provider} card={c} />)}</div>

      {isNative() && healthPlatform() && (
        <Card title={healthPlatform() === "apple_health" ? "Apple Health" : "Health Connect"}>
          <p className="text-sm text-text-secondary">
            Optional. Bring workouts, sleep and heart data from your phone into Catch — only the types you choose, only after you confirm a preview.
          </p>
          <Link to="/settings/health" className={buttonClass("secondary", "md", "mt-3")}>
            Set up
          </Link>
        </Card>
      )}

      <Card tone="inset" title="Sync health">
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
