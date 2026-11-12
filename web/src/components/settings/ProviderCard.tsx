import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { fetchAiModels, saveCoachSettings, setActiveAi, testAiProvider, deleteAiKey } from "../../lib/api";
import { maskedKey, STATUS_GLYPH, STATUS_LABEL, statusDetailText, statusTone } from "../../lib/aiProviders";
import type { AiProviderCard, AiTestResult, CoachSettings, ModelPrice } from "../../lib/types";
import { Card } from "../ui/Card";
import { ProviderKeySheet } from "./ProviderKeySheet";

const inputCls = "min-h-11 min-w-0 rounded-md border border-border bg-surface-2 px-3 text-sm text-text-primary placeholder:text-text-tertiary";
const btn = "min-h-11 rounded-md border border-border px-4 text-sm font-medium text-text-primary transition-colors hover:border-accent disabled:opacity-50";

const TONE: Record<string, string> = {
  good: "border-band-green/40 text-band-green",
  bad: "border-band-red/40 text-band-red-text",
  warn: "border-band-yellow/50 text-text-primary",
  quiet: "border-border text-text-tertiary",
};

export function ProviderCard({ card, settings }: { card: AiProviderCard; settings: CoachSettings | undefined }) {
  const queryClient = useQueryClient();
  const [sheet, setSheet] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [test, setTest] = useState<AiTestResult | null>(null);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["ai-providers"] });
    queryClient.invalidateQueries({ queryKey: ["coach-settings"] });
  };

  const models = useQuery({ queryKey: ["ai-models", card.id], queryFn: () => fetchAiModels(card.id), enabled: card.configured });
  const testMutation = useMutation({
    mutationFn: () => testAiProvider(card.id),
    onSuccess: (r) => {
      setTest(r);
      refresh();
      queryClient.invalidateQueries({ queryKey: ["ai-models", card.id] });
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteAiKey(card.id),
    onSuccess: () => {
      setConfirmRemove(false);
      setTest(null);
      refresh();
    },
  });
  const activate = useMutation({ mutationFn: () => setActiveAi(card.id, card.model ?? undefined), onSuccess: refresh });
  const saveModel = useMutation({
    mutationFn: (model: string) => saveCoachSettings({ models: { [card.id]: model } }),
    onSuccess: refresh,
  });
  const saveUrl = useMutation({ mutationFn: (url: string) => saveCoachSettings({ ollama_base_url: url || null }), onSuccess: refresh });
  const savePrice = useMutation({
    mutationFn: (p: { model: string; price: ModelPrice }) => saveCoachSettings({ prices: { [p.model]: p.price } }),
    onSuccess: refresh,
  });

  const tone = statusTone(card.status);
  const detail = statusDetailText(card);
  const modelList = models.data?.models ?? [];
  const selected = modelList.find((m) => m.id === card.model);
  const price = card.model ? settings?.prices?.[card.model] : undefined;
  const visionNote =
    card.model && selected && selected.vision === false ? "This model can't read photos, so meal and PM5 photo features won't work with it." : null;

  return (
    <Card title={card.label}>
      <div className="flex flex-col gap-3" data-testid={`provider-card-${card.id}`}>
        <div className="flex flex-wrap items-center gap-2">
          <span
            data-testid={`status-${card.id}`}
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${TONE[tone]}`}
          >
            <span aria-hidden="true">{STATUS_GLYPH[card.status]}</span>
            {STATUS_LABEL[card.status]}
          </span>
          {card.active && <span className="rounded-full border border-accent/40 bg-accent/10 px-2.5 py-1 text-xs font-medium text-accent">Active</span>}
          {card.needs_key && card.configured && <span className="font-mono-nums text-xs text-text-tertiary">Key {maskedKey(card.last4)}</span>}
        </div>

        {detail && <p className="text-sm text-text-secondary">{detail}</p>}
        {!card.configured && (
          <p className="text-sm text-text-tertiary">
            {card.needs_key ? `Add your own ${card.label} key to use it. You pay ${card.label} directly.` : "Runs on your own machine — add its address to use it."}
          </p>
        )}

        {card.id === "ollama" && (
          <label className="flex flex-col gap-1.5 text-sm text-text-secondary">
            Ollama address
            <input
              defaultValue={card.base_url ?? ""}
              placeholder="http://laptop.tailnet:11434"
              inputMode="url"
              autoCapitalize="none"
              spellCheck={false}
              onBlur={(e) => e.target.value !== (card.base_url ?? "") && saveUrl.mutate(e.target.value.trim())}
              className={inputCls}
            />
          </label>
        )}

        {card.configured && (
          <div className="flex flex-col gap-1.5">
            <label className="flex flex-col gap-1.5 text-sm text-text-secondary">
              Model
              <select
                value={card.model ?? ""}
                onChange={(e) => e.target.value && saveModel.mutate(e.target.value)}
                disabled={models.isLoading || modelList.length === 0}
                className={inputCls}
                data-testid={`model-${card.id}`}
              >
                <option value="">{models.isLoading ? "Loading models…" : modelList.length ? "Choose a model" : "No models available"}</option>
                {card.model && !modelList.some((m) => m.id === card.model) && <option value={card.model}>{card.model}</option>}
                {modelList.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.display_name}
                    {m.vision === false ? " (no photos)" : ""}
                  </option>
                ))}
              </select>
            </label>
            {models.data?.error && <p className="text-xs text-text-tertiary">{models.data.error}</p>}
            {visionNote && <p className="text-xs text-text-tertiary">{visionNote}</p>}
          </div>
        )}

        {card.configured && card.model && card.id !== "ollama" && (
          <details className="text-sm text-text-secondary">
            <summary className="min-h-11 cursor-pointer content-center">Prices for {card.model} (optional)</summary>
            <p className="mb-2 text-xs text-text-tertiary">
              Dollars per million tokens, from your provider's pricing page. Without these Catch counts tokens but shows cost as unknown, not $0.
            </p>
            <div className="flex flex-wrap gap-3">
              {(["input", "output"] as const).map((k) => (
                <label key={k} className="flex flex-col gap-1 text-xs">
                  {k === "input" ? "Input" : "Output"} $/M
                  <input
                    type="number"
                    min={0}
                    step={0.01}
                    defaultValue={price?.[k] ?? ""}
                    onBlur={(e) => savePrice.mutate({ model: card.model!, price: { ...price, [k]: e.target.value ? Number(e.target.value) : undefined } })}
                    className={`${inputCls} w-28`}
                  />
                </label>
              ))}
            </div>
          </details>
        )}

        <div className="flex flex-wrap gap-2 border-t border-border pt-3">
          {card.configured && !card.active && (
            <button type="button" onClick={() => activate.mutate()} disabled={activate.isPending} className={btn}>
              Make active
            </button>
          )}
          {card.configured && (
            <button type="button" onClick={() => testMutation.mutate()} disabled={testMutation.isPending} className={btn}>
              {testMutation.isPending ? "Testing…" : "Test connection"}
            </button>
          )}
          {card.needs_key && (
            <button type="button" onClick={() => setSheet(true)} className={btn}>
              {card.configured ? "Replace key" : "Add key"}
            </button>
          )}
          {card.needs_key && card.configured && !confirmRemove && (
            <button type="button" onClick={() => setConfirmRemove(true)} className="min-h-11 px-2 text-sm font-medium text-band-red-text hover:underline">
              Remove key
            </button>
          )}
        </div>

        {confirmRemove && (
          <div role="group" aria-label="Confirm removing the key" className="flex flex-col gap-2 rounded-md border border-border p-3 text-sm text-text-secondary">
            <p>
              Remove your {card.label} key? Your conversations and coach memory stay. {card.active ? "The coach will stop answering until you pick another provider." : ""}
            </p>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => remove.mutate()} disabled={remove.isPending} className="min-h-11 rounded-md border border-band-red/40 px-4 text-sm font-medium text-band-red-text">
                {remove.isPending ? "Removing…" : "Remove key"}
              </button>
              <button type="button" onClick={() => setConfirmRemove(false)} className={btn}>
                Keep it
              </button>
            </div>
          </div>
        )}

        {test && (
          <p role="status" data-testid={`test-${card.id}`} className={`text-sm ${test.ok ? "text-band-green" : "text-band-red-text"}`}>
            {test.ok ? `Connected${test.model_count != null ? ` — ${test.model_count} models` : ""}` : test.message}
          </p>
        )}
      </div>
      {card.needs_key && <ProviderKeySheet card={card} open={sheet} onOpenChange={setSheet} />}
    </Card>
  );
}
