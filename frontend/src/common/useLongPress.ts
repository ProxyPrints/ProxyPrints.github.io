/**
 * Pointer-events-based long-press detection (Proposal C part (a),
 * docs/proposals/proposal-c-context-menu-restyle.md) - the approved implementation choice over
 * a library dependency, since the gesture itself is simple: start a timer on touch-down, fire
 * if it elapses undisturbed, cancel on any meaningful movement or on lift-off.
 *
 * touch-only by design (checks e.pointerType) - mouse users already get the same menu via
 * onContextMenu (real right-click), and a mouse "long press" would fight with this element's
 * other mouse interactions (dnd-kit's sortable drag handle, the slot's own click-to-select).
 *
 * Never calls preventDefault on pointerdown/pointermove - doing so before the press threshold
 * elapses would block the browser's own scroll gesture, which starts on the same first touch
 * frame a long-press does. Move-cancels-it (see MOVE_TOLERANCE_PX) is what actually distinguishes
 * a long-press from a scroll: a real scroll moves well past this tolerance almost immediately.
 */

import { useRef } from "react";

const MOVE_TOLERANCE_PX = 10;

export interface LongPressHandlers {
  onPointerDown: (event: React.PointerEvent) => void;
  onPointerMove: (event: React.PointerEvent) => void;
  onPointerUp: (event: React.PointerEvent) => void;
  onPointerCancel: (event: React.PointerEvent) => void;
}

export function useLongPress(
  onLongPress: (clientX: number, clientY: number) => void,
  delayMs = 500
): LongPressHandlers {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const originRef = useRef<{ x: number; y: number } | null>(null);

  const clear = () => {
    if (timerRef.current != null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    originRef.current = null;
  };

  const onPointerDown = (event: React.PointerEvent) => {
    if (event.pointerType !== "touch") {
      return;
    }
    const { clientX, clientY } = event;
    originRef.current = { x: clientX, y: clientY };
    timerRef.current = setTimeout(() => {
      onLongPress(clientX, clientY);
      clear();
    }, delayMs);
  };

  const onPointerMove = (event: React.PointerEvent) => {
    if (originRef.current == null) {
      return;
    }
    const dx = event.clientX - originRef.current.x;
    const dy = event.clientY - originRef.current.y;
    if (Math.sqrt(dx * dx + dy * dy) > MOVE_TOLERANCE_PX) {
      clear();
    }
  };

  return {
    onPointerDown,
    onPointerMove,
    onPointerUp: clear,
    onPointerCancel: clear,
  };
}
