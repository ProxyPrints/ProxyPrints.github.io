import { useEffect, useState } from "react";

interface ElementAnchor {
  x: number;
  y: number;
  width: number;
}

/**
 * Tracks a target element's centre point and width relative to a container element's box,
 * via callback refs (so `anchor` naturally becomes available/unavailable as the target
 * mounts and unmounts, e.g. while the queue card is still loading) - used to pin the
 * Planeswalker queue's starburst background to the subject card itself rather than to the
 * centre of the (dynamically growing/shrinking) container, so the burst doesn't drift when
 * sibling content - like the candidate printing grid - loads in beside it.
 */
export function useElementAnchor(): {
  containerRef: (el: HTMLElement | null) => void;
  targetRef: (el: HTMLElement | null) => void;
  anchor: ElementAnchor | null;
} {
  const [containerEl, setContainerEl] = useState<HTMLElement | null>(null);
  const [targetEl, setTargetEl] = useState<HTMLElement | null>(null);
  const [anchor, setAnchor] = useState<ElementAnchor | null>(null);

  useEffect(() => {
    if (containerEl == null || targetEl == null) {
      setAnchor(null);
      return;
    }

    const measure = () => {
      const containerRect = containerEl.getBoundingClientRect();
      const targetRect = targetEl.getBoundingClientRect();
      setAnchor({
        x: targetRect.left - containerRect.left + targetRect.width / 2,
        y: targetRect.top - containerRect.top + targetRect.height / 2,
        width: targetRect.width,
      });
    };

    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(containerEl);
    observer.observe(targetEl);
    return () => observer.disconnect();
  }, [containerEl, targetEl]);

  return { containerRef: setContainerEl, targetRef: setTargetEl, anchor };
}
