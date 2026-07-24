/**
 * The editor-completion package's §7.5/R3 extraction (docs/proposals - the "editor completion"
 * left-panel-fidelity round, item E6/X5). Pulls CardDetailedViewModal.tsx's body content out into
 * region-level, independently-mountable sub-blocks - CardMetaTable, CardIdentifierCopy,
 * CardDownloadFavorite, PrintingTagsBlock, ReportBlock - plus CardDetailedViewBody, which
 * recomposes them in the modal's own exact order. This is deliberately NOT one blob: the /display
 * left rail's new demoted "Card Details"/"Printing Tags"/"Report" sections (DisplayPage.tsx) mount
 * CardMetaTable+CardDownloadFavorite, PrintingTagsBlock, and ReportBlock individually, each as its
 * own collapsed AutofillCollapse per the D3 hierarchy - never the whole modal body, since the rail
 * already has its own art-selection surface (Select Version) and doesn't want a second full-size
 * card image render.
 *
 * Acceptance test for this extraction (per the task's own directive) is
 * tests/visual/CardDetailedViewModal.visual.spec.ts staying green UNMODIFIED - its aria snapshot
 * asserts the modal's exact DOM shape, so CardDetailedViewModal.tsx's own render below must stay
 * byte-for-byte equivalent to what CardDetailedViewModal.tsx used to render inline. Every
 * sub-block is fully self-contained (fetches its own hook data - useGetLanguagesQuery,
 * useDoImageDownload, useTagDisplayName, selectRemoteBackendURL - rather than threading it down
 * from a parent), so the rail can mount any one of them standalone with no shared parent state.
 *
 * `showAddToProjectForm` (default true, matching every existing behavior) is the one prop this
 * extraction adds: AddCardToProjectForm is dropped from the rail's own Card Details mount (the
 * slot is already in the project there - see DisplayPage.tsx's Rail composition) but stays in the
 * modal, unconditionally, exactly as before.
 */
import React, { useState } from "react";
import Badge from "react-bootstrap/Badge";
import Button from "react-bootstrap/Button";

import { PrintingConsensusResponse } from "@/common/schema_types";
import { useTagDisplayName } from "@/common/tagDisplayNames";
import { CardDocument, useAppDispatch, useAppSelector } from "@/common/types";
import { imageSizeToMBString, toTitleCase } from "@/common/utils";
import { ArtistSupportLink } from "@/components/ArtistSupportLink";
import { AutofillTable } from "@/components/AutofillTable";
import { ClickToCopy } from "@/components/ClickToCopy";
import { RightPaddedIcon } from "@/components/icon";
import { SetIcon } from "@/components/SetIcon";
import { AttributeVotingPanel } from "@/features/attributeVoting/AttributeVotingPanel";
import { AddCardToFavorites } from "@/features/card/AddCardToFavorites";
import { AddCardToProjectForm } from "@/features/card/AddCardToProjectForm";
import { useDoImageDownload } from "@/features/download/downloadImages";
import { PrintingTagPicker } from "@/features/printingTags/PrintingTagPicker";
import { ReportCardPanel } from "@/features/reporting/ReportCardPanel";
import { useGetLanguagesQuery } from "@/store/api";
import { selectRemoteBackendURL } from "@/store/slices/backendSlice";
import { setNotification } from "@/store/slices/toastsSlice";

//# region CardIdentifierCopy

interface CardIdentifierCopyProps {
  identifier: string;
}

/** Thin, named wrapper over ClickToCopy for the metadata table's "Identifier" row - exported per
 * the extraction's own sub-block list (E6) so a future standalone "copy identifier" affordance
 * doesn't need to re-derive this from CardMetaTable. */
export function CardIdentifierCopy({ identifier }: CardIdentifierCopyProps) {
  return <ClickToCopy text={identifier} />;
}

//# endregion

//# region CardMetaTable

interface CardMetaTableProps {
  cardDocument: CardDocument;
  /** Rail-delegacy round (rev #2/RD7, SPEC-rail-delegacy.md) - additive, optional. `false` drops
   * the "Canonical Card" row (the printing set/collector identifier) from this table entirely -
   * the /display rail's "More details" disclosure passes this, since the same identifier already
   * lives ONCE, always-visible, in the D14 confidence band (`ConfidenceElement.tsx`); repeating it
   * here would be exactly the "static second copy" RD7 rules out. `undefined`/`true` (every other
   * caller - the classic card-detail modal, CardDetailedViewBody's own default composition)
   * preserves today's behavior unchanged - that surface has no D14 band of its own. */
  showCanonicalCard?: boolean;
}

export function CardMetaTable({
  cardDocument,
  showCanonicalCard = true,
}: CardMetaTableProps) {
  const getLanguagesQuery = useGetLanguagesQuery();
  const getTagDisplayName = useTagDisplayName();
  const languageNameByCode = Object.fromEntries(
    (getLanguagesQuery.data ?? []).map((row) => [row.code, row.name])
  );

  return (
    <AutofillTable
      headers={[]}
      data={[
        [
          "Source Name",
          cardDocument.sourceExternalLink != null &&
          cardDocument.sourceExternalLink.length > 0 ? (
            <a href={cardDocument.sourceExternalLink} target="_blank">
              {cardDocument.sourceVerbose}
            </a>
          ) : (
            cardDocument.sourceVerbose
          ),
        ],
        ["Source Type", cardDocument.sourceType],
        ["Class", toTitleCase(cardDocument.cardType)],
        [
          "Identifier",
          <CardIdentifierCopy
            key={`${cardDocument.identifier}-click-to-copy`}
            identifier={cardDocument.identifier}
          />,
        ],
        ["Language", languageNameByCode[cardDocument.language]],
        [
          "Tags",
          cardDocument.tags.length > 0 ? (
            <>
              {cardDocument.tags.map((tag) => (
                <Badge key={tag} pill>
                  {getTagDisplayName(tag)}
                </Badge>
              ))}
            </>
          ) : (
            "Untagged"
          ),
        ],
        ["Resolution", `${cardDocument.dpi} DPI`],
        ["Date Created", cardDocument.dateCreated],
        ["Date Modified", cardDocument.dateModified],
        ["File Size", imageSizeToMBString(cardDocument.size, 2)],
        ...(showCanonicalCard
          ? [
              [
                "Canonical Card",
                cardDocument.canonicalCard ? (
                  <>
                    <SetIcon
                      expansionCode={cardDocument.canonicalCard.expansionCode}
                    />{" "}
                    {cardDocument.canonicalCard.expansionCode.toUpperCase()}{" "}
                    {cardDocument.canonicalCard.collectorNumber}
                  </>
                ) : (
                  "Unknown"
                ),
              ],
            ]
          : []),
        [
          "Canonical Aritst",
          cardDocument.canonicalArtist != null ? (
            <ArtistSupportLink artistName={cardDocument.canonicalArtist.name}>
              {cardDocument.canonicalArtist.name}
            </ArtistSupportLink>
          ) : (
            "Unknown"
          ),
        ],
      ]}
      hover={true}
      alignment={"left"}
      uniformWidth={false}
      columnLabels={true}
    />
  );
}

//# endregion

//# region CardDownloadFavorite

interface CardDownloadFavoriteProps {
  cardDocument: CardDocument;
}

export function CardDownloadFavorite({
  cardDocument,
}: CardDownloadFavoriteProps) {
  const dispatch = useAppDispatch();
  const queueImageDownload = useDoImageDownload();

  return (
    <>
      {cardDocument.sourceType === "Google Drive" && (
        <div className="d-grid gap-0">
          <Button
            variant="primary"
            onClick={async () => {
              queueImageDownload(cardDocument);
              dispatch(
                setNotification([
                  Math.random().toString(),
                  {
                    name: "Enqueued Downloads",
                    message: `Enqueued 1 image download!`,
                    level: "info",
                  },
                ])
              );
            }}
          >
            <RightPaddedIcon bootstrapIconName="cloud-arrow-down" /> Download
            Image
          </Button>
        </div>
      )}
      <AddCardToFavorites cardDocument={cardDocument} />
    </>
  );
}

//# endregion

//# region PrintingTagsBlock

interface PrintingTagsBlockProps {
  cardDocument: CardDocument;
}

export function PrintingTagsBlock({ cardDocument }: PrintingTagsBlockProps) {
  const backendURL = useAppSelector(selectRemoteBackendURL);
  const [printingConsensus, setPrintingConsensus] =
    useState<PrintingConsensusResponse | null>(null);

  return (
    <>
      <hr />
      <h5>What&apos;s That Card?</h5>
      <p className="text-muted small mb-2">
        Help us figure out which real-world printing this card is!
      </p>
      <PrintingTagPicker
        cardIdentifier={cardDocument.identifier}
        cardName={cardDocument.name}
        onConsensusChange={setPrintingConsensus}
      />
      {printingConsensus != null &&
        printingConsensus.resolvedPrinting == null &&
        backendURL != null && (
          <>
            <hr />
            <AttributeVotingPanel
              backendURL={backendURL}
              cardIdentifier={cardDocument.identifier}
              confidentlyKnownArtistName={
                cardDocument.canonicalArtist != null &&
                !cardDocument.canonicalArtistIsFromVoteOnly
                  ? cardDocument.canonicalArtist.name
                  : null
              }
            />
          </>
        )}
    </>
  );
}

//# endregion

//# region ReportBlock

interface ReportBlockProps {
  cardDocument: CardDocument;
}

export function ReportBlock({ cardDocument }: ReportBlockProps) {
  return <ReportCardPanel cardDocument={cardDocument} />;
}

//# endregion

//# region CardDetailedViewBody

interface CardDetailedViewBodyProps {
  cardDocument: CardDocument;
  /** Modal-only (default true, matching every existing behavior): the rail's own "Card Details"
   * mount passes false, since the slot is already in the project there - see this file's own
   * module comment. */
  showAddToProjectForm?: boolean;
}

/** The modal's own right-column content (heading + metadata + download/favorite + add-to-project
 * + report + printing tags), recomposed from the sub-blocks above in their original order - this
 * is what makes CardDetailedViewModal.tsx's own render byte-for-byte unchanged. */
export function CardDetailedViewBody({
  cardDocument,
  showAddToProjectForm = true,
}: CardDetailedViewBodyProps) {
  return (
    <>
      <h4>{cardDocument.name}</h4>
      <CardMetaTable cardDocument={cardDocument} />
      <CardDownloadFavorite cardDocument={cardDocument} />
      {showAddToProjectForm && (
        <AddCardToProjectForm cardDocument={cardDocument} />
      )}
      <ReportBlock cardDocument={cardDocument} />
      <PrintingTagsBlock cardDocument={cardDocument} />
    </>
  );
}

//# endregion
