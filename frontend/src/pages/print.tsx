import Head from "next/head";
import Link from "next/link";
import React from "react";

import { ProjectName } from "@/common/constants";
import { useAppSelector } from "@/common/types";
import { NoBackendDefault } from "@/components/NoBackendDefault";
import { FinishedMyProject } from "@/features/export/FinishedMyProject";
import Footer from "@/features/ui/Footer";
import { ProjectContainer } from "@/features/ui/Layout";
import {
  useAnyBackendConfigured,
  useProjectName,
} from "@/store/slices/backendSlice";
import { selectIsProjectEmpty } from "@/store/slices/projectSlice";
require("bootstrap-icons/font/bootstrap-icons.css");

/**
 * Proposal H ADDENDUM D10/F5 (docs/proposals/proposal-h-display-layout-spec.md, issue #275) - a
 * thin route wrapper mounting `FinishedMyProject` (the MakePlayingCards/NotMPC/PringlePrints
 * supplier tabs + the PDF sub-tab), mirroring `pages/myDecks.tsx`'s own
 * `MyDecksPage`/`pages/shared.tsx`'s `SharedDeckPage` wrapper pattern - compose, don't fork.
 * `FinishedMyProject.tsx` itself is UNCHANGED; this file only gives it a standalone route so the
 * Finish footer's "Print / Export →" button (FinishFooter.tsx, via PrePrintSaveGate.tsx) has
 * somewhere to client-side-navigate to (D9's pre-print persist step runs BEFORE this navigation,
 * never after). The classic /editor "Print!" tab keeps mounting the same component unchanged too
 * (ProjectEditor.tsx's own `PrintPanel`) - both /display and /editor now funnel here.
 *
 * Deliberately NOT built here (D10's own owner addendum, explicitly out of THIS issue's scope per
 * the task that shipped this file): the tab REORDER (owner order: PDF · MakePlayingCards ·
 * NotMPC · PringlePrints, PDF default - today's array order/default is unchanged) and the PDF
 * tab's own preview removal (`showPreview={false}` prop plumbing so /display's own center sheet
 * region becomes the sole preview). Both are tracked as their own follow-up against this same
 * D10 addendum, not silently dropped - see that doc's own change inventory.
 */
function PrintPageOrDefault() {
  const anyBackendConfigured = useAnyBackendConfigured();
  const isProjectEmpty = useAppSelector(selectIsProjectEmpty);

  if (!anyBackendConfigured) {
    return <NoBackendDefault requirement="any" />;
  }

  // A direct/bookmarked nav here with nothing in the project yet has nothing for
  // FinishedMyProject to usefully show (no cards to export) - point back at the funnel's own
  // entry point rather than rendering an empty PDF/supplier-instructions surface.
  if (isProjectEmpty) {
    return (
      <div className="p-4 text-center" data-testid="print-page-empty-state">
        <p>Your project is empty - there&apos;s nothing to print yet.</p>
        <Link href="/display">Head to Display to add some cards</Link>
      </div>
    );
  }

  return <FinishedMyProject />;
}

export default function Print() {
  const projectName = useProjectName();
  return (
    <ProjectContainer gutter={0}>
      <Head>
        <title>{`${projectName} Print`}</title>
        <meta
          name="description"
          content={`Finish and export your ${ProjectName} project.`}
        />
      </Head>
      <PrintPageOrDefault />
      <Footer />
    </ProjectContainer>
  );
}
