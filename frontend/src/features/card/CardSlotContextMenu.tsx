/**
 * Proposal C part (a) (docs/proposals/proposal-c-context-menu-restyle.md) - the right-click
 * (desktop) / long-press (mobile) trigger for the same actions CardSlot.tsx's existing 3-dot
 * dropdown already exposes. Deliberately NOT built on react-bootstrap's <Dropdown> (which
 * anchors its menu to a <Dropdown.Toggle> element via Popper, not an arbitrary point) - instead
 * renders plain elements using Bootstrap's own `.dropdown-menu`/`.dropdown-item` CSS classes
 * directly, fixed-positioned at the trigger's (x, y), so it's visually identical to the 3-dot
 * menu (same theme, same classes) without fighting Popper's anchor-element assumption.
 */

import React, { useEffect, useRef } from "react";

import { RightPaddedIcon } from "@/components/icon";
import { CardSlotMenuAction } from "@/features/card/CardSlotMenuActions";

interface CardSlotContextMenuProps {
  actions: CardSlotMenuAction[];
  position: { x: number; y: number };
  onClose: () => void;
}

export function CardSlotContextMenu({
  actions,
  position,
  onClose,
}: CardSlotContextMenuProps) {
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (
        menuRef.current != null &&
        !menuRef.current.contains(event.target as Node)
      ) {
        onClose();
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    // capture phase so this fires before the trigger's own onContextMenu/long-press handler
    // could otherwise immediately reopen the menu it just closed.
    document.addEventListener("pointerdown", handlePointerDown, true);
    document.addEventListener("keydown", handleKeyDown, true);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown, true);
      document.removeEventListener("keydown", handleKeyDown, true);
    };
  }, [onClose]);

  return (
    <div
      ref={menuRef}
      role="menu"
      data-testid="card-slot-context-menu"
      className="dropdown-menu show"
      style={{
        position: "fixed",
        top: position.y,
        left: position.x,
        zIndex: 1050, // matches bootstrap's $zindex-dropdown
      }}
    >
      {actions.map((action) => (
        <button
          key={action.key}
          type="button"
          role="menuitem"
          className="dropdown-item"
          onClick={() => {
            action.onClick();
            onClose();
          }}
        >
          <RightPaddedIcon bootstrapIconName={action.bootstrapIconName} />
          {action.label}
        </button>
      ))}
    </div>
  );
}
