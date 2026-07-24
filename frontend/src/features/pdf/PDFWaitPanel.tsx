/**
 * PDF-generation wait experience round (SPEC-cardback-pdfwait.md §D, `PKG2`) - two pieces mounted
 * from `PDFGenerator.tsx`:
 *
 *   - `PDFProgressBox` (2a) - a real Bootstrap `ProgressBar`, determinate while the real
 *     `imageFetchProgress {completed,total}` signal exists (`pdfRenderService.onImageProgress`),
 *     honest indeterminate (`animated striped`) for the `@react-pdf/renderer` layout/encode phase
 *     that exposes NO progress callback (Annex A-3, `PB1`), and a green "done" bar. Replaces the
 *     old bare `pdf-image-fetch-progress` text line (kept as the SAME `data-testid` on the
 *     determinate label, so nothing that greps for it breaks).
 *   - `PDFWaitGameEmbed` (2b) - the right column while generation runs: a chrome frame around
 *     `<QuestionFeed>` rendered VERBATIM (no forked component, no new voting mechanic - the exact
 *     `/whatsthat` funnel, docs/features/printing-tags.md) plus a persistent build-status ribbon
 *     so the PDF's own progress stays visible while playing. Lazy-loaded via
 *     `next/dynamic({ssr:false})` and only imported once generation actually starts (memory-safety
 *     constraint `D.4`/`MS1`/`MS3` - never eagerly bundled/instantiated on the print page, and torn
 *     down (unmounted) the instant generation finishes - see `PDFGenerator.tsx`'s own
 *     `waitPhase` derivation for the teardown trigger).
 */
import styled from "@emotion/styled";
import dynamic from "next/dynamic";
import React from "react";
import ProgressBar from "react-bootstrap/ProgressBar";
import Spinner from "react-bootstrap/Spinner";

export type PDFWaitPhase = "idle" | "fetching" | "assembling" | "done";

// Lazy-loaded ONLY once a caller actually mounts <PDFWaitGameEmbed> (which PDFGenerator.tsx only
// does once isDownloading/isSavingToDrive is true) - never eagerly bundled/instantiated while a
// user is still configuring the PDF (D.4/2c's own binding constraint).
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
  background: #22303f;
  border: 1px solid #16202b;
  padding: 10px 12px;
`;

const ProgressLabel = styled.div`
  font-size: 12px;
  color: #ebebeb;
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;

  .pfrac {
    font-variant-numeric: tabular-nums;
    color: #8fa0b0;
  }
`;

const ProgressSub = styled.div<{ $done?: boolean }>`
  font-size: 11px;
  color: ${(props) => (props.$done ? "#8fe08f" : "#8fa0b0")};
  margin-top: 6px;
`;

const SeamTag = styled.span`
  display: block;
  font-size: 11px;
  color: #ffd76a;
  margin-top: 6px;
`;

// §D.1/§G - the assembling phase is genuinely indeterminate (no progress callback exists for
// `@react-pdf/renderer`'s own layout/encode phase). react-bootstrap's <ProgressBar> always emits
// a real `aria-valuenow` from its `now` prop with no way to suppress it via props (the component
// sets it AFTER spreading incoming props, so it can't be overridden) - passing `now={100}` would
// announce a false "100% complete" to a screen reader mid-assembly, exactly the "no false
// numeric" rule §G is binding on. This is a plain, hand-built indeterminate track instead:
// `aria-busy="true"`, no `aria-valuenow`/`aria-valuemin`/`aria-valuemax` at all.
const IndeterminateTrack = styled.div`
  height: 10px;
  background: #16202b;
  overflow: hidden;
`;

const IndeterminateFill = styled.div`
  height: 100%;
  width: 100%;
  background-color: #df6919;
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
  imageFetchProgress: { completed: number; total: number } | null;
}

/** §D.1 (2a) - the progress bar `PDFGenerator.tsx` mounts whenever `phase !== "idle"`. */
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
        <SeamTag>
          seam 2a: &quot;total&quot; is approximate (undercounts duplicate
          cards) → shown as &quot;~N&quot;, never a false 100%.
        </SeamTag>
      </ProgressBox>
    );
  }

  if (phase === "assembling") {
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
        <SeamTag>
          seam 2a: the assemble/encode phase exposes no progress callback (Annex
          A-3) → honest indeterminate bar, not a placeholder number.
        </SeamTag>
      </ProgressBox>
    );
  }

  return (
    <ProgressBox data-testid="pdf-progress">
      <ProgressLabel>
        <span>✓ PDF ready</span>
        <span className="pfrac">cards.pdf</span>
      </ProgressLabel>
      <ProgressBar now={100} variant="success" data-testid="pdf-progress-bar" />
      <ProgressSub $done>Saved to your device.</ProgressSub>
    </ProgressBox>
  );
}

const EmbedFrame = styled.div`
  border: 1px solid #16202b;
  background: #22303f;
  height: 100%;
  min-height: 420px;
  display: flex;
  flex-direction: column;
`;

const EmbedHead = styled.div`
  background: #2b3e50;
  border-bottom: 1px solid #16202b;
  padding: 8px 12px;
  display: flex;
  align-items: center;
  gap: 8px;

  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #df6919;
  }

  .h {
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #8fa0b0;
  }

  .lz {
    margin-left: auto;
    font-size: 10px;
    color: #8fa0b0;
    font-family: "Courier New", monospace;
  }
`;

const BuildRibbon = styled.div<{ $done?: boolean }>`
  background: #0b1520;
  border-bottom: 1px solid #16202b;
  padding: 6px 12px;
  font-size: 11px;
  color: ${(props) => (props.$done ? "#8fe08f" : "#ebebeb")};
  display: flex;
  align-items: center;
  gap: 8px;

  .mini {
    flex: 1;
    height: 6px;
    background: #16202b;
    overflow: hidden;
  }

  .mini .b {
    height: 100%;
    background: ${(props) => (props.$done ? "#5cb85c" : "#df6919")};
  }
`;

const EmbedBody = styled.div`
  flex: 1;
  overflow-y: auto;
`;

export interface PDFWaitGameEmbedProps {
  phase: "fetching" | "assembling";
  imageFetchProgress: { completed: number; total: number } | null;
}

/** §D.2 (2b) - the right column while generation runs. Renders `<QuestionFeed>` verbatim inside
 * a chrome frame with a persistent build-status ribbon. */
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
        <span className="lz">
          lazy-loaded on generate · torn down on finish
        </span>
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
          color: "#8fa0b0",
          textAlign: "center",
          padding: "6px 12px",
          borderTop: "1px solid #16202b",
        }}
      >
        Each answer is submitted the instant you tap — leaving mid-card never
        loses a vote.
      </div>
    </EmbedFrame>
  );
}
