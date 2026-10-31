export function PlaceholderPage({ title }: { title: string }) {
  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center gap-2 text-center">
      <h1 className="text-lg font-semibold text-text-primary">{title}</h1>
      <p className="max-w-xs text-sm text-text-tertiary">Coming in a later session.</p>
    </div>
  );
}
