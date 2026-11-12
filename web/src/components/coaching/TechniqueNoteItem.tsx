import type { TechniqueNote } from "../../lib/types";
import { formatShortDate } from "../../lib/format";
import { TECHNIQUE_CATEGORIES } from "./labels";
import { PrivacyBadge } from "./PrivacyBadge";

export function TechniqueNoteItem({ note, onEdit, showWorkout }: { note: TechniqueNote; onEdit: (n: TechniqueNote) => void; showWorkout?: boolean }) {
  const cat = TECHNIQUE_CATEGORIES.find((c) => c.value === note.category)?.label ?? note.category;
  return (
    <li className="flex flex-col gap-2 rounded-md border border-border p-3" data-testid="technique-note" data-visibility={note.visibility}>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="rounded-full border border-border px-2 py-0.5 font-medium text-text-primary">{cat}</span>
        <PrivacyBadge visibility={note.visibility} />
        {note.piece && <span className="text-text-tertiary">piece {note.piece.piece_type}</span>}
        {note.date && <span className="text-text-tertiary">{formatShortDate(note.date)}</span>}
        {showWorkout && note.workout && <span className="text-text-tertiary">{note.workout.title}</span>}
      </div>
      <p className="whitespace-pre-wrap text-sm text-text-primary">{note.text}</p>
      {note.media.length > 0 && (
        <ul className="flex flex-wrap gap-x-3 gap-y-1 text-sm">
          {note.media.map((m) => (
            <li key={m.url}>
              <a href={m.url} target="_blank" rel="noopener noreferrer" className="text-accent underline">
                {m.label || m.url}
              </a>
            </li>
          ))}
        </ul>
      )}
      <button type="button" onClick={() => onEdit(note)} className="min-h-11 self-start text-sm font-medium text-accent">
        Edit
      </button>
    </li>
  );
}
