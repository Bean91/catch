// A one-way channel from native event sources (appUrlOpen, a notification tap) to the router hook. Kept out of React so a
// notification that launched the app cold is not lost before the first render: the hook replays what arrived before it mounted.
import type { DeepLinkTarget } from "./deepLinkTargets";

type Listener = (t: DeepLinkTarget) => void;
const listeners = new Set<Listener>();
const backlog: DeepLinkTarget[] = [];

export function emitDeepLink(target: DeepLinkTarget): void {
  if (listeners.size === 0) {
    backlog.push(target);
    if (backlog.length > 5) backlog.shift();
    return;
  }
  for (const l of listeners) l(target);
}

export function onDeepLink(listener: Listener): () => void {
  listeners.add(listener);
  for (const t of backlog.splice(0)) listener(t);
  return () => listeners.delete(listener);
}
