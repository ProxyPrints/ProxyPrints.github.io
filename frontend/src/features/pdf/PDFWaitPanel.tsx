/**
 * Issue #811 - the PDF-generation wait experience, homed in the shared export pipeline
 * (`features/pdf/`, beside `pdfDownload.tsx`) rather than a page component. It originally lived
 * beside `/print`'s `PDFGenerator.tsx` (deleted outright by #813's retirement of that page,
 * `git show e98839ef^:frontend/src/features/pdf/PDFWaitPanel.tsx` for the prior version) and
 * went missing from the editor's own export because nothing re-mounted it once the editor
 * started reusing `pdfDownload.tsx`'s render pipeline directly. Living here instead of beside a
 * caller means any surface that renders a PDF through that pipeline gets a real wait experience
 * by construction, not by remembering to import one.
 *
 * Two pieces:
 *   - `PDFProgressBox` - a real Bootstrap `ProgressBar`, determinate while the real
 *     `imageFetchProgress {completed,total}` signal exists (`pdfRenderService.onImageProgress`,
 *     threaded through `pdfDownload.tsx`'s `setProgress` callback), honest indeterminate
 *     (`animated striped`) for the `@react-pdf/renderer` layout/encode phase that exposes NO
 *     progress callback - there is no third state to report once fetching completes, only an
 *     honest "still working, can't say how much longer".
 *   - `PDFWaitGameEmbed` - a chrome frame around `<QuestionFeed>` rendered verbatim (no forked
 *     component, no new voting mechanic - the exact `/whatsthat` funnel,
 *     docs/features/printing-tags.md) plus a persistent build-status ribbon so the PDF's own
 *     progress stays visible while playing. Lazy-loaded via `next/dynamic({ssr:false})` and only
 *     imported once a caller actually mounts it (which only happens once generation has actually
 *     started - see `derivePDFWaitPhase` below) - never eagerly bundled into a caller's initial
 *     bundle just because that caller imports this module.
 */
import styled from "@emotion/styled";
import dynamic from "next/dynamic";
import React from "react";
import ProgressBar from "react-bootstrap/ProgressBar";
import Spinner from "react-bootstrap/Spinner";

export type PDFWaitPhase = "idle" | "fetching" | "assembling";

export interface PDFImageFetchProgress {
  completed: number;
  total: number;
}

/**
 * Pure - derives the two-phase wait signal from state a caller already owns: the render
 * pipeline's own isDownloading/isSavingToDrive (collapsed into `generating` by the caller) plus
 * the live image-fetch progress `pdfDownload.tsx`'s `setProgress` callback already populates.
 * Not a hook (no internal state of its own) - callers keep owning `generating` and
 * `imageFetchProgress` however they already do, this just names the derivation once instead of
 * re-deriving it at every mount point.
 */
export function derivePDFWaitPhase(
  generating: boolean,
  imageFetchProgress: PDFImageFetchProgress | null
): PDFWaitPhase {
  if (!generating) {
    return "idle";
  }
  return imageFetchProgress == null ||
    imageFetchProgress.completed < imageFetchProgress.total
    ? "fetching"
    : "assembling";
}

// Lazy-loaded ONLY once a caller actually mounts <PDFWaitGameEmbed> - never eagerly
// bundled/instantiated just because a caller imports this module to read PDFWaitPhase or render
// PDFProgressBox.
const LazyQuestionFeed = dynamic(
  () =>
    import("@/features/questionFeed/QuestionFeed").then((m) => m.QuestionFeed),
  {
    ssr: false,
    loading: () => (
      <div className="d-flex justify-content-center p-4">
        <Spinner animation="border" size="sm" />
      </div>
    ),
  }
);

const ProgressBox = styled.div`
  margin-top: 12px;
  background: var(--theme-raised-bg);
  border: 1px solid var(--theme-divider);
  padding: 10px 12px;
`;

const ProgressLabel = styled.div`
  font-size: 12px;
  color: var(--bs-body-color);
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;

  .pfrac {
    font-variant-numeric: tabular-nums;
    color: var(--theme-muted);
  }
`;

const ProgressSub = styled.div`
  font-size: 11px;
  color: var(--theme-muted);
  margin-top: 6px;
`;

// The assembling phase is genuinely indeterminate (no progress callback exists for
// `@react-pdf/renderer`'s own layout/encode phase). react-bootstrap's <ProgressBar> always emits
// a real `aria-valuenow` from its `now` prop with no way to suppress it via props (the component
// sets it AFTER spreading incoming props, so it can't be overridden) - passing `now={100}` would
// announce a false "100% complete" to a screen reader mid-assembly. This is a plain, hand-built
// indeterminate track instead: `aria-busy="true"`, no `aria-valuenow`/`aria-valuemin`/
// `aria-valuemax` at all.
const IndeterminateTrack = styled.div`
  height: 10px;
  background: var(--theme-divider);
  overflow: hidden;
`;

const IndeterminateFill = styled.div`
  height: 100%;
  width: 100%;
  background-color: var(--bs-primary);
  background-image: linear-gradient(
    45deg,
    rgba(255, 255, 255, 0.18) 25%,
    transparent 25%,
    transparent 50%,
    rgba(255, 255, 255, 0.18) 50%,
    rgba(255, 255, 255, 0.18) 75%,
    transparent 75%,
    transparent
  );
  background-size: 1rem 1rem;
  animation: pdf-wait-barstripe 1s linear infinite;

  @keyframes pdf-wait-barstripe {
    from {
      background-position: 1rem 0;
    }
    to {
      background-position: 0 0;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    animation: none;
  }
`;

export interface PDFProgressBoxProps {
  phase: PDFWaitPhase;
  imageFetchProgress: PDFImageFetchProgress | null;
}

/** The progress bar a caller mounts whenever `phase !== "idle"`. */
export function PDFProgressBox({
  phase,
  imageFetchProgress,
}: PDFProgressBoxProps) {
  if (phase === "idle") {
    return null;
  }

  if (phase === "fetching") {
    const completed = imageFetchProgress?.completed ?? 0;
    const total = imageFetchProgress?.total ?? 0;
    // `total` is approximate (undercounts duplicate cards - pdf.worker.ts's own comment), so the
    // bar is capped at 99% and never claims a false 100% before the phase genuinely ends.
    const percent = total > 0 ? Math.min((completed / total) * 100, 99) : 0;
    return (
      <ProgressBox data-testid="pdf-progress">
        <ProgressLabel data-testid="pdf-image-fetch-progress">
          <span>Fetching images…</span>
          <span className="pfrac">
            {completed} of ~{total}
          </span>
        </ProgressLabel>
        <ProgressBar now={percent} data-testid="pdf-progress-bar" />
        <ProgressSub>
          Full-resolution fetches are paced to the image CDN - a large deck can
          take a few minutes.
        </ProgressSub>
      </ProgressBox>
    );
  }

  return (
    <ProgressBox data-testid="pdf-progress">
      <ProgressLabel>
        <span>Assembling PDF…</span>
        <span className="pfrac">images done</span>
      </ProgressLabel>
      {/* Hand-built, not <ProgressBar> - see IndeterminateTrack's own comment: no
          aria-valuenow (no false numeric), aria-busy only. */}
      <IndeterminateTrack
        role="progressbar"
        aria-busy="true"
        aria-label="Assembling PDF"
        data-testid="pdf-progress-bar"
      >
        <IndeterminateFill />
      </IndeterminateTrack>
      <ProgressSub>Laying out pages &amp; encoding.</ProgressSub>
    </ProgressBox>
  );
}

const EmbedFrame = styled.div`
  border: 1px solid var(--theme-divider);
  background: var(--theme-raised-bg);
  height: 100%;
  min-height: 360px;
  display: flex;
  flex-direction: column;
`;

const EmbedHead = styled.div`
  background: var(--theme-band-bg);
  border-bottom: 1px solid var(--theme-divider);
  padding: 8px 12px;
  display: flex;
  align-items: center;
  gap: 8px;

  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--bs-primary);
  }

  .h {
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--theme-muted);
  }
`;

const BuildRibbon = styled.div`
  background: #0b1520;
  border-bottom: 1px solid var(--theme-divider);
  padding: 6px 12px;
  font-size: 11px;
  color: var(--bs-body-color);
  display: flex;
  align-items: center;
  gap: 8px;

  .mini {
    flex: 1;
    height: 6px;
    background: var(--theme-divider);
    overflow: hidden;
  }

  .mini .b {
    height: 100%;
    background: var(--bs-primary);
  }
`;

const EmbedBody = styled.div`
  flex: 1;
  overflow-y: auto;
`;

export interface PDFWaitGameEmbedProps {
  phase: "fetching" | "assembling";
  imageFetchProgress: PDFImageFetchProgress | null;
}

/** The right-column embed a caller mounts while generation runs (`phase === "fetching" ||
 * phase === "assembling"` - never for "idle", and there is no "done" phase to mount it for,
 * since a caller tears this down the instant generation stops). */
export function PDFWaitGameEmbed({
  phase,
  imageFetchProgress,
}: PDFWaitGameEmbedProps) {
  const completed = imageFetchProgress?.completed ?? 0;
  const total = imageFetchProgress?.total ?? 0;
  const percent = total > 0 ? Math.min((completed / total) * 100, 99) : 0;
  const ribbonLabel =
    phase === "fetching" ? "Building your PDF…" : "Assembling your PDF…";
  return (
    <EmbedFrame data-testid="pdf-wait-game">
      <EmbedHead>
        <span className="dot" aria-hidden="true" />
        <span className="h">While your PDF builds — help identify a card?</span>
      </EmbedHead>
      <BuildRibbon data-testid="pdf-wait-game-ribbon">
        <span>{ribbonLabel}</span>
        <span className="mini">
          <span className="b" style={{ width: `${percent}%` }} />
        </span>
      </BuildRibbon>
      <EmbedBody>
        <LazyQuestionFeed />
      </EmbedBody>
      <div
        style={{
          fontSize: 10,
          color: "var(--theme-muted)",
          textAlign: "center",
          padding: "6px 12px",
          borderTop: "1px solid var(--theme-divider)",
        }}
      >
        Each answer is submitted the instant you tap — leaving mid-card never
        loses a vote.
      </div>
    </EmbedFrame>
  );
}
