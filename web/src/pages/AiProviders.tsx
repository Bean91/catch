import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { fetchAiProviders, fetchAiUsage, fetchCoachSettings } from "../lib/api";
import { formatTokens } from "../lib/aiProviders";
import { Card } from "../components/ui/Card";
import { CardSkeleton } from "../components/ui/Skeleton";
import { ProviderCard } from "../components/settings/ProviderCard";

export function AiProvidersPage() {
  const providers = useQuery({ queryKey: ["ai-providers"], queryFn: fetchAiProviders });
  const settings = useQuery({ queryKey: ["coach-settings"], queryFn: fetchCoachSettings });
  const usage = useQuery({ queryKey: ["ai-usage"], queryFn: fetchAiUsage });

  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <div>
        <Link to="/settings" className="text-sm font-medium text-accent hover:underline">
          ← Settings
        </Link>
        <h1 className="mt-1 text-lg font-semibold text-text-primary">AI providers</h1>
        <p className="mt-1 text-sm text-text-secondary">
          Catch never pays for AI. Each provider uses your own key, stored encrypted on the server and never shown again. With no provider set up,
          AI features stay off.
        </p>
      </div>

      {providers.isLoading && <CardSkeleton lines={4} />}
      {providers.isError && <p className="text-sm text-band-red-text">Couldn't load providers.</p>}
      {providers.data && !providers.data.active && (
        <p role="status" data-testid="no-active-provider" className="rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-text-secondary">
          No provider is active, so the coach and the photo features are off. Add a key below, or make a configured provider active.
        </p>
      )}
      {providers.data?.providers.map((card) => <ProviderCard key={card.id} card={card} settings={settings.data} />)}

      <Card title="Usage Catch has recorded">
        {usage.data ? (
          <div className="flex flex-col gap-2 text-sm text-text-secondary" data-testid="ai-usage">
            <p>
              Today: {formatTokens(usage.data.today.tokens)} tokens
              {usage.data.today.cap_usd != null && <> · ${usage.data.today.spend_usd.toFixed(2)} of ${usage.data.today.cap_usd.toFixed(2)} cap</>}
            </p>
            {Object.entries(usage.data.by_provider).map(([id, u]) => (
              <p key={id}>
                {providers.data?.providers.find((c) => c.id === id)?.label ?? id}, last {usage.data!.days} days: {formatTokens(u.tokens)} tokens · {u.turns} requests ·{" "}
                {u.unpriced_turns === u.turns ? "cost unknown (no price entered)" : `$${u.cost_usd.toFixed(2)}`}
                {u.unpriced_turns > 0 && u.unpriced_turns < u.turns && ` (${u.unpriced_turns} unpriced)`}
              </p>
            ))}
            {Object.keys(usage.data.by_provider).length === 0 && <p className="text-text-tertiary">Nothing recorded yet.</p>}
            <p className="border-t border-border pt-2 text-xs text-text-tertiary">
              This is only what Catch itself sent. Your providers don't offer a balance through an API key, so none is shown — check it in their
              consoles.
            </p>
          </div>
        ) : (
          <p className="text-sm text-text-tertiary">Loading…</p>
        )}
      </Card>
    </div>
  );
}
