import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent } from "react";
import { movePlanned } from "../../lib/api";
import { dayLabel } from "../../lib/dates";
import { haptic } from "../../lib/native/haptics";
import type { PlannedWorkout } from "../../lib/types";
import { useToast } from "../ui/Toast";
import { invalidateCalendar } from "./PlannedWorkoutSheet";

const HOLD_MS = 350;
const MOUSE_SLOP_PX = 6;
const TOUCH_SLOP_PX = 8;

type Drag = { plan: PlannedWorkout; x: number; y: number; over: string | null };

function dayAt(x: number, y: number): string | null {
  const el = document.elementFromPoint(x, y)?.closest<HTMLElement>("[data-drop-date]");
  return el?.dataset.dropDate ?? null;
}

/** Session 36 follow-up: drag a planned session onto another day of the week view to move it (POST /api/planned/{id}/move — the
 * same call the sheet's date field makes, so a series keeps every other occurrence and a link stays as it is). A mouse drags after a
 * few pixels; a finger has to press and hold first, so an ordinary swipe still scrolls the page. Tapping still opens the sheet,
 * which stays the keyboard and screen-reader way to move a session. Every move offers Undo. */
export function usePlanDrag() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [drag, setDrag] = useState<Drag | null>(null);
  const pending = useRef<{ plan: PlannedWorkout; x: number; y: number; type: string; timer: number | null; el: HTMLElement; id: number } | null>(null);
  const active = useRef(false);
  const swallowClick = useRef(false);

  const move = useMutation({
    mutationFn: ({ id, date }: { id: number; date: string }) => movePlanned(id, date),
    onSettled: () => invalidateCalendar(qc),
  });

  const finish = useCallback(
    (x: number | null, y: number | null) => {
      const p = pending.current;
      if (p?.timer) window.clearTimeout(p.timer);
      pending.current = null;
      if (!active.current || !p) {
        active.current = false;
        return;
      }
      active.current = false;
      swallowClick.current = true;
      window.setTimeout(() => (swallowClick.current = false), 0);
      setDrag(null);
      const target = x != null && y != null ? dayAt(x, y) : null;
      if (!target || target === p.plan.date) return;
      const from = p.plan.date;
      move.mutate(
        { id: p.plan.id, date: target },
        {
          onSuccess: () => {
            haptic("success");
            toast(`Moved “${p.plan.title}” to ${dayLabel(target)}.`, {
              action: { label: "Undo", onClick: () => move.mutate({ id: p.plan.id, date: from }) },
            });
          },
          onError: (e) => toast((e as Error).message || "Couldn't move that session.", { tone: "error" }),
        },
      );
    },
    [move, toast],
  );

  const begin = useCallback(() => {
    const p = pending.current;
    if (!p) return;
    active.current = true;
    p.timer = null;
    try {
      p.el.setPointerCapture(p.id);
    } catch {
      /* the pointer may already be gone */
    }
    haptic("selection");
    setDrag({ plan: p.plan, x: p.x, y: p.y, over: dayAt(p.x, p.y) });
  }, []);

  // A finger that has started a drag must not also scroll the page: a non-passive touchmove listener cancels the scroll only while
  // a drag is active, so a swipe that never held still scrolls as usual.
  useEffect(() => {
    const stop = (e: TouchEvent) => {
      if (active.current) e.preventDefault();
    };
    document.addEventListener("touchmove", stop, { passive: false });
    return () => document.removeEventListener("touchmove", stop);
  }, []);

  const handlers = (plan: PlannedWorkout) => ({
    onPointerDown: (e: ReactPointerEvent<HTMLElement>) => {
      if (e.button !== 0 || move.isPending) return;
      pending.current = { plan, x: e.clientX, y: e.clientY, type: e.pointerType, timer: null, el: e.currentTarget, id: e.pointerId };
      if (e.pointerType !== "mouse") pending.current.timer = window.setTimeout(begin, HOLD_MS);
    },
    onPointerMove: (e: ReactPointerEvent<HTMLElement>) => {
      const p = pending.current;
      if (!p) return;
      if (active.current) {
        setDrag((d) => (d ? { ...d, x: e.clientX, y: e.clientY, over: dayAt(e.clientX, e.clientY) } : d));
        return;
      }
      const dist = Math.hypot(e.clientX - p.x, e.clientY - p.y);
      if (p.type === "mouse") {
        if (dist > MOUSE_SLOP_PX) begin();
      } else if (dist > TOUCH_SLOP_PX) {
        // moved before the hold finished: this is a scroll, not a drag
        if (p.timer) window.clearTimeout(p.timer);
        pending.current = null;
      }
    },
    onPointerUp: (e: ReactPointerEvent<HTMLElement>) => finish(e.clientX, e.clientY),
    onPointerCancel: () => {
      setDrag(null);
      finish(null, null);
    },
    onClickCapture: (e: ReactMouseEvent) => {
      if (swallowClick.current) {
        e.preventDefault();
        e.stopPropagation();
      }
    },
    onContextMenu: (e: ReactMouseEvent) => {
      if (pending.current && pending.current.type !== "mouse") e.preventDefault();
    },
  });

  const ghost = drag ? (
    <div
      aria-hidden
      data-testid="plan-drag-ghost"
      className="glass-primary glass-dense glass-elevated pointer-events-none fixed z-50 max-w-[16rem] -translate-x-1/2 -translate-y-[130%] truncate rounded-md border border-accent bg-surface px-3 py-1.5 text-sm font-medium text-text-primary shadow-[var(--shadow-2)]"
      style={{ left: drag.x, top: drag.y }}
    >
      {drag.plan.title}
      {drag.over && drag.over !== drag.plan.date ? <span className="ml-1 text-xs text-accent">→ {dayLabel(drag.over)}</span> : null}
    </div>
  ) : null;

  return { handlers, ghost, dragging: drag, overDate: drag?.over ?? null };
}
