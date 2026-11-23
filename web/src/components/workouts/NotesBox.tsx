import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { fetchNote, saveNote } from "../../lib/api";
import { Card } from "../ui/Card";
import { buttonClass } from "../ui/Button";
import { controlBase } from "../ui/Field";

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
    <Card title="Day note & RPE">
      <p className="mb-2 text-xs text-text-tertiary">
        One journal entry per calendar day (used as the sRPE strain fallback when a session has no HR) — separate from the
        per-workout notes/RPE in the Edit card above.
      </p>
      <textarea
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setDirty(true);
        }}
        placeholder="How did it feel?"
        rows={3}
        className={controlBase + " w-full resize-none"}
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
          className={buttonClass("primary", "md", "shrink-0")}
        >
          {save.isPending ? "Saving…" : "Save"}
        </button>
      </div>
    </Card>
  );
}
