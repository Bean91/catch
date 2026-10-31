import { motion } from "framer-motion";
import { useReducedMotion } from "../../lib/useReducedMotion";

// The one "lane/water-line" motif the design brief allows — a single hairline, used once
// per screen (here, under the recovery ring), drawn in on load and never looping.
export function Waterline() {
  const reduced = useReducedMotion();
  return (
    <motion.div
      aria-hidden
      className="h-px w-24"
      style={{
        background: "linear-gradient(90deg, transparent, var(--accent), transparent)",
        transformOrigin: "center",
      }}
      initial={{ scaleX: reduced ? 1 : 0, opacity: reduced ? 0.6 : 0 }}
      animate={{ scaleX: 1, opacity: 0.6 }}
      transition={{ duration: reduced ? 0 : 0.8, delay: reduced ? 0 : 0.3, ease: [0.16, 1, 0.3, 1] }}
    />
  );
}
