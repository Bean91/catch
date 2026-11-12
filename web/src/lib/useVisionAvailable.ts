import { useQuery } from "@tanstack/react-query";
import { fetchAiProviders } from "./api";

/** Whether the active AI provider can read photos (meal estimate, PM5 screen). False — and the
 *  photo entry points are absent, not merely erroring — when no provider is set up, no model is
 *  chosen, or the provider can't do vision. */
export function useVisionAvailable(enabled = true): boolean {
  const query = useQuery({ queryKey: ["ai-providers"], queryFn: fetchAiProviders, enabled });
  return query.data?.vision.available ?? false;
}
