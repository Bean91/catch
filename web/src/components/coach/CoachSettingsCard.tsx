import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  createToken,
  deleteAnthropicKey,
  deleteToken,
  fetchCoachModels,
  fetchCoachSettings,
  fetchTokens,
  saveCoachSettings,
  setAnthropicKey,
  testCoachConnection,
} from "../../lib/api";
import { formatRelativeTime } from "../../lib/format";
import type { CoachProviderName } from "../../lib/types";
import { Card } from "../ui/Card";

const inputCls = "min-h-11 rounded-md border border-border bg-surface-2 px-3 text-sm text-text-primary placeholder:text-text-tertiary";

export function CoachSettingsCard() {
  const queryClient = useQueryClient();
  const settingsQuery = useQuery({ queryKey: ["coach-settings"], queryFn: fetchCoachSettings });
  const tokensQuery = useQuery({ queryKey: ["coach-tokens"], queryFn: fetchTokens });

  const [keyInput, setKeyInput] = useState("");
  const [testResult, setTestResult] = useState<{ ok: boolean; error?: string; model_count?: number } | null>(null);
  const [newTokenName, setNewTokenName] = useState("");
  const [mintedToken, setMintedToken] = useState<string | null>(null);

  const provider = settingsQuery.data?.provider ?? "anthropic";
  const modelsQuery = useQuery({
    queryKey: ["coach-models", provider],
    queryFn: () => fetchCoachModels(provider),
    enabled: !!settingsQuery.data && (provider === "ollama" ? !!settingsQuery.data.ollama_base_url : settingsQuery.data.anthropic_key.configured),
  });

  const save = useMutation({
    mutationFn: (patch: Record<string, unknown>) => saveCoachSettings(patch),
    onSuccess: (data) => queryClient.setQueryData(["coach-settings"], data),
  });

  const saveKey = useMutation({
    mutationFn: () => setAnthropicKey(keyInput),
    onSuccess: (anthropic_key) => {
      setKeyInput("");
      queryClient.setQueryData(["coach-settings"], (prev: typeof settingsQuery.data) => (prev ? { ...prev, anthropic_key } : prev));
    },
  });

  const removeKey = useMutation({
    mutationFn: () => deleteAnthropicKey(),
    onSuccess: () => queryClient.setQueryData(["coach-settings"], (prev: typeof settingsQuery.data) => (prev ? { ...prev, anthropic_key: { configured: false, last4: null } } : prev)),
  });

  const testConnection = useMutation({
    mutationFn: () => testCoachConnection(),
    onSuccess: setTestResult,
  });

  const createDeviceToken = useMutation({
    mutationFn: () => createToken(newTokenName),
    onSuccess: (row) => {
      setMintedToken(row.token);
      setNewTokenName("");
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
        <div className="flex gap-2">
          {(["anthropic", "ollama"] as CoachProviderName[]).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => save.mutate({ provider: p })}
              className={`min-h-11 rounded-md border px-4 text-sm font-medium transition-colors ${
                provider === p ? "border-accent text-accent" : "border-border text-text-tertiary"
              }`}
            >
              {p === "anthropic" ? "Anthropic (bring your own key)" : "Ollama (local, on your laptop)"}
            </button>
          ))}
        </div>

        {provider === "anthropic" ? (
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm text-text-secondary">
                {s.anthropic_key.configured ? `Key configured, ending …${s.anthropic_key.last4}` : "No key configured"}
              </span>
              {s.anthropic_key.configured && (
                <button type="button" onClick={() => removeKey.mutate()} className="text-xs font-medium text-band-red-text hover:underline">
                  Remove
                </button>
              )}
            </div>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (keyInput.trim()) saveKey.mutate();
              }}
              className="flex flex-wrap gap-2"
            >
              <input
                type="password"
                autoComplete="off"
                placeholder="sk-ant-…"
                value={keyInput}
                onChange={(e) => setKeyInput(e.target.value)}
                className={`${inputCls} min-w-[220px] flex-1`}
              />
              <button
                type="submit"
                disabled={!keyInput.trim() || saveKey.isPending}
                className="min-h-11 rounded-md bg-accent px-4 text-sm font-medium text-accent-contrast hover:opacity-90 disabled:opacity-50"
              >
                {saveKey.isPending ? "Saving…" : "Save key"}
              </button>
            </form>

            <label className="flex flex-col gap-1.5 text-sm text-text-secondary sm:flex-row sm:items-center sm:gap-3">
              Model
              <select
                value={s.anthropic_model ?? ""}
                onChange={(e) => save.mutate({ anthropic_model: e.target.value })}
                className={inputCls}
              >
                <option value="">Default (newest Sonnet)</option>
                {modelsQuery.data?.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.display_name}
                  </option>
                ))}
              </select>
            </label>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <label className="flex flex-col gap-1.5 text-sm text-text-secondary">
              Ollama URL (reachable over Tailscale)
              <input
                placeholder="http://laptop.tailnet:11434"
                defaultValue={s.ollama_base_url ?? ""}
                onBlur={(e) => save.mutate({ ollama_base_url: e.target.value || null })}
                className={inputCls}
              />
            </label>
            <label className="flex flex-col gap-1.5 text-sm text-text-secondary">
              Model (only tool-capable models are listed)
              <select value={s.ollama_model ?? ""} onChange={(e) => save.mutate({ ollama_model: e.target.value || null })} className={inputCls}>
                <option value="">Choose a model…</option>
                {modelsQuery.data?.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.display_name}
                  </option>
                ))}
              </select>
            </label>
            {modelsQuery.data?.length === 0 && (
              <p className="text-xs text-text-tertiary">No tool-capable models found — is the laptop awake and reachable?</p>
            )}
          </div>
        )}

        <div className="flex items-center gap-3 border-t border-border pt-3">
          <button
            type="button"
            onClick={() => testConnection.mutate()}
            disabled={testConnection.isPending}
            className="min-h-11 rounded-md border border-border px-4 text-sm font-medium text-text-primary transition-colors hover:border-accent disabled:opacity-50"
          >
            {testConnection.isPending ? "Testing…" : "Test connection"}
          </button>
          {testResult && (
            <span className={`text-sm ${testResult.ok ? "text-band-green" : "text-band-red-text"}`}>
              {testResult.ok ? `Connected (${testResult.model_count} models)` : testResult.error}
            </span>
          )}
        </div>

        <label className="flex items-center gap-3 border-t border-border pt-3 text-sm text-text-secondary">
          Daily spend cap (USD, blocks new coach requests once hit — leave blank for no cap)
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

        <div className="border-t border-border pt-3">
          <h4 className="mb-2 text-sm font-medium text-text-primary">Device tokens (for the MCP server / Claude Desktop)</h4>
          <div className="flex flex-col gap-2">
            {tokensQuery.data?.map((t) => (
              <div key={t.id} className="flex items-center justify-between gap-2 text-sm text-text-secondary">
                <span>
                  {t.name} · last used {formatRelativeTime(t.last_used_at)}
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
            className="mt-2 flex gap-2"
          >
            <input
              placeholder="e.g. laptop"
              value={newTokenName}
              onChange={(e) => setNewTokenName(e.target.value)}
              className={`${inputCls} flex-1`}
            />
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
