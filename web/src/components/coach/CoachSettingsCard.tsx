import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { createToken, deleteToken, fetchAiProviders, fetchCoachSettings, fetchTokens, saveCoachSettings } from "../../lib/api";
import { formatRelativeTime } from "../../lib/format";
import { Card } from "../ui/Card";

const inputCls = "min-h-11 rounded-md border border-border bg-surface-2 px-3 text-sm text-text-primary placeholder:text-text-tertiary";

export function CoachSettingsCard() {
  const queryClient = useQueryClient();
  const settingsQuery = useQuery({ queryKey: ["coach-settings"], queryFn: fetchCoachSettings });
  const tokensQuery = useQuery({ queryKey: ["coach-tokens"], queryFn: fetchTokens });
  const providersQuery = useQuery({ queryKey: ["ai-providers"], queryFn: fetchAiProviders });

  const [newTokenName, setNewTokenName] = useState("");
  const [mintedToken, setMintedToken] = useState<string | null>(null);
  const [coachToken, setCoachToken] = useState(false);
  const [coachName, setCoachName] = useState("");

  const save = useMutation({
    mutationFn: (patch: Record<string, unknown>) => saveCoachSettings(patch),
    onSuccess: (data) => queryClient.setQueryData(["coach-settings"], data),
  });

  const createDeviceToken = useMutation({
    mutationFn: () => createToken(newTokenName, coachToken ? "coach" : "athlete", coachToken ? coachName : undefined),
    onSuccess: (row) => {
      setMintedToken(row.token);
      setNewTokenName("");
      setCoachToken(false);
      setCoachName("");
      queryClient.invalidateQueries({ queryKey: ["coach-tokens"] });
    },
  });

  const removeToken = useMutation({ mutationFn: (id: number) => deleteToken(id), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["coach-tokens"] }) });

  if (settingsQuery.isLoading || !settingsQuery.data) {
    return (
      <Card title="AI coach">
        <p className="text-sm text-text-tertiary">Loading…</p>
      </Card>
    );
  }
  const s = settingsQuery.data;

  return (
    <Card title="AI coach">
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-2" data-testid="ai-provider-summary">
          <p className="text-sm text-text-secondary">
            {providersQuery.data?.active
              ? `Active provider: ${providersQuery.data.providers.find((p) => p.id === providersQuery.data!.active)?.label}`
              : "No AI provider is set up — AI features are off until you add your own key."}
          </p>
          <Link to="/settings/ai" className="min-h-11 content-center text-sm font-medium text-accent hover:underline">
            AI providers →
          </Link>
        </div>

        <label className="flex items-center gap-3 border-t border-border pt-3 text-sm text-text-secondary">
          Daily spend cap (USD, blocks new AI requests once hit — leave blank for no cap)
          <input
            type="number"
            min={0}
            step={0.5}
            placeholder="none"
            defaultValue={s.daily_cap_usd ?? ""}
            onBlur={(e) => save.mutate({ daily_cap_usd: e.target.value ? Number(e.target.value) : null })}
            className={`${inputCls} w-24`}
          />
        </label>

        <label className="flex items-center gap-3 border-t border-border pt-3 text-sm text-text-secondary">
          Daily token cap (also applies to models you haven't priced)
          <input
            type="number"
            min={0}
            step={10000}
            placeholder="none"
            defaultValue={s.daily_token_cap ?? ""}
            onBlur={(e) => save.mutate({ daily_token_cap: e.target.value ? Number(e.target.value) : null })}
            className={`${inputCls} w-28`}
          />
        </label>

        <div className="border-t border-border pt-3">
          <h4 className="mb-2 text-sm font-medium text-text-primary">Device tokens (for the MCP server / Claude Desktop)</h4>
          <div className="flex flex-col gap-2">
            {tokensQuery.data?.map((t) => (
              <div key={t.id} className="flex items-center justify-between gap-2 text-sm text-text-secondary">
                <span>
                  {t.name}
                  {t.role === "coach" && (
                    <span data-testid="coach-token-badge" className="ml-1 rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 text-xs text-accent">
                      Coach{t.display_name ? ` · ${t.display_name}` : ""}
                    </span>
                  )}{" "}
                  · last used {formatRelativeTime(t.last_used_at)}
                </span>
                <button type="button" onClick={() => removeToken.mutate(t.id)} className="text-xs font-medium text-band-red-text hover:underline">
                  Revoke
                </button>
              </div>
            ))}
            {tokensQuery.data?.length === 0 && <p className="text-sm text-text-tertiary">No device tokens yet.</p>}
          </div>
          {mintedToken && (
            <div className="mt-2 rounded-md border border-accent/30 bg-accent/10 p-2.5 text-xs text-text-primary">
              <p className="mb-1 font-medium">Copy this now — it won't be shown again:</p>
              <code className="font-mono-nums break-all">{mintedToken}</code>
            </div>
          )}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              createDeviceToken.mutate();
            }}
            className="mt-2 flex flex-wrap gap-2"
          >
            <input
              placeholder="e.g. laptop"
              value={newTokenName}
              onChange={(e) => setNewTokenName(e.target.value)}
              className={`${inputCls} min-w-0 flex-1`}
            />
            <label className="flex min-h-11 w-full items-center gap-2 text-sm text-text-secondary">
              <input type="checkbox" checked={coachToken} onChange={(e) => setCoachToken(e.target.checked)} className="h-4 w-4" />
              A coach's token — sees only notes and feedback you share, and the workout library
            </label>
            {coachToken && (
              <input placeholder="Coach's name (shown on their feedback)" value={coachName} onChange={(e) => setCoachName(e.target.value)} className={`${inputCls} w-full`} />
            )}
            <button
              type="submit"
              disabled={!newTokenName.trim() || createDeviceToken.isPending}
              className="min-h-11 rounded-md border border-border px-4 text-sm font-medium text-text-primary transition-colors hover:border-accent disabled:opacity-50"
            >
              Create token
            </button>
          </form>
        </div>

        <Link to="/settings/memory" className="text-sm font-medium text-accent hover:underline">
          Manage coach memory (events, goals, facts) →
        </Link>
      </div>
    </Card>
  );
}
