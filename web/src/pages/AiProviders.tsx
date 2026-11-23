import { useQuery } from "@tanstack/react-query";
import { fetchAiProviders, fetchAiUsage, fetchCoachSettings } from "../lib/api";
import { formatTokens } from "../lib/aiProviders";
import { Card } from "../components/ui/Card";
import { CardSkeleton, Skeleton } from "../components/ui/Skeleton";
import { ErrorState } from "../components/ui/EmptyState";
import { DefinitionList } from "../components/ui/DataList";
import { Notice } from "../components/ui/Notice";
import { PageHeader } from "../components/ui/PageHeader";
import { ProviderCard } from "../components/settings/ProviderCard";

export function AiProvidersPage() {
  const providers = useQuery({ queryKey: ["ai-providers"], queryFn: fetchAiProviders, staleTime: 5 * 60_000 });
  const settings = useQuery({ queryKey: ["coach-settings"], queryFn: fetchCoachSettings, staleTime: 5 * 60_000 });
  const usage = useQuery({ queryKey: ["ai-usage"], queryFn: fetchAiUsage });

  return (
    <div className="flex flex-col gap-4 lg:gap-5">
      <PageHeader
        back={{ to: "/settings", label: "Settings" }}
        eyebrow="Coach and AI"
        title="AI providers"
        subtitle="Catch never pays for AI. Each provider uses your own key, stored encrypted on the server and never shown again. With no provider set up, AI features stay off."
      />

      {providers.isLoading && <CardSkeleton lines={4} />}
      {providers.isError && <ErrorState message="Couldn't load providers." onRetry={() => providers.refetch()} />}
      {providers.data && !providers.data.active && (
        <Notice tone="warn" role="status" testId="no-active-provider">
          No provider is active, so the coach and the photo features are off. Add a key below, or make a configured provider active.
        </Notice>
      )}
      {providers.data?.providers.map((card) => <ProviderCard key={card.id} card={card} settings={settings.data} />)}

      <Card title="Usage Catch has recorded">
        {usage.data ? (
          <div className="flex flex-col gap-2 text-sm text-text-secondary" data-testid="ai-usage">
            <DefinitionList
              layout="rows"
              mono={false}
              items={[
                {
                  key: "today",
                  label: "Today",
                  value: (
                    <>
                      {formatTokens(usage.data.today.tokens)} tokens
                      {usage.data.today.cap_usd != null && <> · ${usage.data.today.spend_usd.toFixed(2)} of ${usage.data.today.cap_usd.toFixed(2)} cap</>}
                    </>
                  ),
                },
                ...Object.entries(usage.data.by_provider).map(([id, u]) => ({
                  key: id,
                  label: `${providers.data?.providers.find((c) => c.id === id)?.label ?? id}, last ${usage.data!.days} days`,
                  value: (
                    <>
                      {formatTokens(u.tokens)} tokens · {u.turns} requests · {u.unpriced_turns === u.turns ? "cost unknown (no price entered)" : `$${u.cost_usd.toFixed(2)}`}
                      {u.unpriced_turns > 0 && u.unpriced_turns < u.turns && ` (${u.unpriced_turns} unpriced)`}
                    </>
                  ),
                })),
              ]}
            />
            {Object.keys(usage.data.by_provider).length === 0 && <p className="text-text-tertiary">Nothing recorded yet.</p>}
            <p className="border-t border-border pt-2 text-xs text-text-tertiary">
              This is only what Catch itself sent. Your providers don't offer a balance through an API key, so none is shown — check it in their
              consoles.
            </p>
          </div>
        ) : usage.isError ? (
          <ErrorState message="Couldn't load usage." onRetry={() => usage.refetch()} />
        ) : (
          <div className="flex flex-col gap-2" aria-busy="true">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        )}
      </Card>
    </div>
  );
}
