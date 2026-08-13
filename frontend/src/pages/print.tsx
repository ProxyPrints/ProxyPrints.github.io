import Head from "next/head";
import Link from "next/link";
import React, { useState } from "react";

import { ProjectName } from "@/common/constants";
import { useAppSelector } from "@/common/types";
import { NoBackendDefault } from "@/components/NoBackendDefault";
import {
  DownloadManager,
  OpenDownloadManagerButton,
} from "@/features/download/DownloadManager";
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
 * `FinishedMyProject.tsx` itself is UNCHANGED; this file only gives it a standalone route.
 * Originally, the classic /editor "Print!" tab (ProjectEditor.tsx's own `PrintPanel`) mounted the
 * same component too, so both /display and /editor funneled here; the Proposal H route swap
 * (2026-07-23, issues #231/#272) unrouted that classic page entirely, and the unified editor's
 * own Finish footer became this route's only live entry point. That button was itself folded into
 * the editor's Export dropdown once Drive save landed there too (`DisplayExportPDF.tsx` - see
 * docs/features/pdf-generator.md's "Editor-native PDF export" section and FinishFooter.tsx's own
 * module comment), so this page now has no in-app entry point at all - only a direct/bookmarked
 * URL reaches it, always with `isProjectEmpty` true below. Kept in-tree rather than deleted since
 * removing it entirely is its own follow-up, not part of the change that retired its funnel.
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
        <Link href="/editor">Head to the editor to add some cards</Link>
      </div>
    );
  }

  return <FinishedMyProject />;
}

export default function Print() {
  const projectName = useProjectName();
  // Nav+footer redesign (2026-07-22, N10) - the cloud download-queue counter/manager (image/
  // XML/decklist/PDF export downloads) used to live in the global navbar, cut from there per
  // the redesign. This page is the other of its two new mounts (the first is FinishFooter.tsx
  // on /display, whose DisplayExportMenu now covers XML/Card Images/Decklist/PDF) - this one
  // covers the same PDF path plus Save PDF to Google Drive and the desktop-tool XML download
  // FinishedMyProject's own PDFGenerator/ProjectDownload trigger, neither of which /display
  // exposes. Both mounts read the same global fileDownloadsSlice, so either always shows every
  // download regardless of which page started it.
  const [showDownloadManager, setShowDownloadManager] = useState(false);
  return (
    <ProjectContainer gutter={0}>
      <Head>
        <title>{`${projectName} Print`}</title>
        <meta
          name="description"
          content={`Finish and export your ${ProjectName} project.`}
        />
      </Head>
      <div className="d-flex justify-content-end px-2 pt-1">
        <OpenDownloadManagerButton
          handleClick={() => setShowDownloadManager(true)}
        />
      </div>
      <DownloadManager
        show={showDownloadManager}
        handleClose={() => setShowDownloadManager(false)}
      />
      <PrintPageOrDefault />
      <Footer />
    </ProjectContainer>
  );
}
