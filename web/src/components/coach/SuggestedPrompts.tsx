const PROMPTS = ["How should I train today?", "Why is my recovery low?", "Plan my week before a 2k test"];

export function SuggestedPrompts({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="flex flex-wrap justify-center gap-2">
      {PROMPTS.map((prompt) => (
        <button
          key={prompt}
          type="button"
          onClick={() => onPick(prompt)}
          className="min-h-11 rounded-full border border-border px-4 text-sm text-text-secondary transition-colors hover:border-accent hover:text-text-primary"
        >
          {prompt}
        </button>
      ))}
    </div>
  );
}
