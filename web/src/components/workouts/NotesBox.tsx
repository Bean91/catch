import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { fetchNote, saveNote } from "../../lib/api";
import { Card } from "../ui/Card";

export function NotesBox({ date }: { date: string }) {
  const queryClient = useQueryClient();
  const { data: note } = useQuery({ queryKey: ["note", date], queryFn: () => fetchNote(date) });
  const [text, setText] = useState("");
  const [rpe, setRpe] = useState<number | null>(null);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (note && !dirty) {
      setText(note.text);
      setRpe(note.rpe);
    }
  }, [note, dirty]);

  const save = useMutation({
    mutationFn: () => saveNote(date, text, rpe),
    onSuccess: () => {
      setDirty(false);
      queryClient.invalidateQueries({ queryKey: ["note", date] });
    },
  });

  return (
    <Card title="Notes & RPE">
      <textarea
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setDirty(true);
        }}
        placeholder="How did it feel?"
        rows={3}
        className="w-full resize-none rounded-md border border-border bg-surface-2 p-3 text-sm text-text-primary placeholder:text-text-tertiary focus-visible:outline-none"
      />
      <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <label className="flex items-center gap-3 text-sm text-text-secondary">
          RPE
          <input
            type="range"
            min={0}
            max={10}
            step={1}
            value={rpe ?? 0}
            onChange={(e) => {
              setRpe(Number(e.target.value));
              setDirty(true);
            }}
            className="w-32 accent-[var(--accent)]"
          />
          <span className="font-mono-nums w-6 text-text-primary">{rpe ?? "—"}</span>
        </label>
        <button
          type="button"
          onClick={() => save.mutate()}
          disabled={save.isPending || !dirty}
          className="min-h-11 shrink-0 rounded-md bg-accent px-4 text-sm font-medium text-accent-contrast transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {save.isPending ? "Saving…" : "Save"}
        </button>
      </div>
    </Card>
  );
}
