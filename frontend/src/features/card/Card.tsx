/**
 * This component is a fundamental UI building block for displaying cards.
 * Displays a card's image, some extra information (its name, its source's name, and its DPI),
 * and has optional props for extending the component to include extra functionality.
 * If being used in a gallery, the previous and next images can be cached for visual smoothness.
 */

import styled from "@emotion/styled";
import Image from "next/image";
import React, {
  memo,
  PropsWithChildren,
  ReactElement,
  Ref,
  useEffect,
  useRef,
  useState,
} from "react";
import BSCard from "react-bootstrap/Card";
import Col from "react-bootstrap/Col";
import OverlayTrigger from "react-bootstrap/OverlayTrigger";
import Tooltip from "react-bootstrap/Tooltip";

import { getCardDataAttributes } from "@/common/cardDom";
import {
  getBucketImageURL,
  getImageKey,
  getWorkerImageURL,
} from "@/common/image";
import { getPrintingMatchLabel } from "@/common/processing";
import { SourceType } from "@/common/schema_types";
import { SearchQuery, useAppDispatch, useAppSelector } from "@/common/types";
import { CardDocument } from "@/common/types";
import { Icon } from "@/components/icon";
import { Spinner } from "@/components/Spinner";
import { useClientSearchContext } from "@/features/clientSearch/clientSearchContext";
import { selectCardDocumentByIdentifier } from "@/store/slices/cardDocumentsSlice";
import { selectIsFavoriteRender } from "@/store/slices/favoritesSlice";
import { showCardDetailedViewModal } from "@/store/slices/modalsSlice";
import { RootState } from "@/store/store";

const HiddenImage = styled(Image)`
  z-index: 0;
  opacity: 0;
`;

// next/image's <Image> forwards unrecognised props straight onto the underlying <img>, so
// these component-only props (used only for this styled-component's own CSS interpolation)
// need filtering at this boundary - otherwise React logs a "does not recognize the ... prop"
// console warning for each one, on every card image rendered anywhere in the app.
const VisibleImage = styled(Image, {
  shouldForwardProp: (prop) =>
    prop !== "imageIsLoading" &&
    prop !== "showDetailedViewOnClick" &&
    prop !== "zIndex",
})<{
  imageIsLoading?: boolean;
  showDetailedViewOnClick?: boolean;
  zIndex?: number;
}>`
  z-index: ${(props) => props.zIndex ?? 1};
  &:hover {
    cursor: ${(props) => (props.showDetailedViewOnClick ? "pointer" : "auto")};
  }
  opacity: ${(props) => (props.imageIsLoading ? 0 : 1)};
`;

const OutlinedBSCardSubtitle = styled(BSCard.Subtitle)`
  outline-style: dashed;
  outline-width: 1px;
  outline-color: #999999;
  transition: outline-style 0.2s ease-in-out, outline-color 0.2s ease-in-out;
  &:hover {
    outline-style: solid;
    outline-color: #ffffff;
    cursor: pointer;
  }
`;

// Replaces the old solid-black error_404*.png assets, which read as a harsh black square at
// grid scale against the card's own #4e5d6c placeholder background - matching that background
// here instead makes a failed fetch (a real production path - dead Drive links) look like a
// designed empty state rather than a rendering glitch.
const ErrorPlaceholder = styled.div`
  position: absolute;
  inset: 0;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  background: var(--bs-secondary);
  color: rgba(255, 255, 255, 0.75);
  text-align: center;
  padding: 0.5rem;

  i {
    font-size: 1.75rem;
  }

  span {
    font-size: 0.8rem;
  }
`;

// A card image fetch that's still pending after SlowLoadHintDelayMS gets a small "still
// loading" hint alongside the spinner - an indefinite spinner with no feedback and no
// timeout is indistinguishable from a genuinely stuck fetch.
const SlowLoadHintDelayMS = 6_000;

const SlowLoadHint = styled.div`
  position: absolute;
  bottom: 8px;
  left: 0;
  right: 0;
  z-index: 2;
  text-align: center;
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.85);
`;

const CardIcon = styled(Icon)`
  width: auto;
  height: auto;
  top: unset;
  left: unset;
  bottom: 8px;
  right: 8px;
  z-index: 2;
  -webkit-text-stroke: 2px black;
`;

// separate corner from CardIcon (favorite heart) so the two never overlap when both apply
const MatchIndicatorIcon = styled(Icon)`
  width: auto;
  height: auto;
  top: unset;
  right: unset;
  bottom: 8px;
  left: 8px;
  z-index: 2;
  -webkit-text-stroke: 2px black;
`;

// Foreign-order resilience Phase 1 (issue #324) - "visually distinct treatment" for an orphan
// (a card addressed only by a Drive file ID this catalog has never indexed). Top corner, clear
// of the existing bottom-corner favorite-heart/printing-match icons. Text comes straight from
// the synthesized CardDocument's own sourceName ("Your file" on this - the author/editor -
// surface; a later phase's shared-deck recipient view can synthesize "Shared file" instead
// without this component needing to know the difference).
const OrphanBadge = styled.span`
  // Bootstrap's .ratio > * rule (the aspect-ratio wrapper every card image sits inside)
  // stretches EVERY direct child to width:100%/height:100%/top:0/left:0 by default - width/
  // height must be overridden back to auto here (same defensive pattern CardIcon/
  // MatchIndicatorIcon below already use), or this badge silently stretches to cover the whole
  // card instead of sitting in its corner (caught only by a real browser render - Jest/jsdom
  // doesn't compute layout, so this class of bug is invisible to unit tests).
  position: absolute;
  top: 8px;
  left: 8px;
  width: auto;
  height: auto;
  z-index: 2;
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(13, 110, 253, 0.85);
  color: #fff;
  pointer-events: none;
`;

type ImageState =
  | "loading-from-bucket"
  | "loading-from-fallback"
  | "loading-from-local-file"
  | "loaded-from-bucket"
  | "loaded-from-fallback"
  | "loaded-from-local-file"
  | "errored";

const useLocalFileImageSrc = (
  cardDocument: CardDocument,
  setImageState: (imageState: ImageState) => void
): string | undefined => {
  const { clientSearchService } = useClientSearchContext();
  const [blobURL, setBlobURL] = useState<string | undefined>(undefined);
  useEffect(() => {
    (async () => {
      if (cardDocument.sourceType === SourceType.LocalFile) {
        const oramaCardDocument = await clientSearchService.getByID(
          cardDocument?.identifier
        );
        if (oramaCardDocument?.params?.sourceType == SourceType.LocalFile) {
          setImageState("loading-from-local-file");
          const file = await oramaCardDocument.params.fileHandle.getFile();
          const url = URL.createObjectURL(file);
          setBlobURL(url);
        }
      }
    })();
  }, [cardDocument?.identifier, clientSearchService, setImageState]);
  return blobURL;
};

export const useImageSrc = (
  cardDocument: CardDocument,
  small: boolean
): {
  imageSrc: string | undefined;
  onLoad: React.ReactEventHandler<HTMLImageElement>;
  onError: React.ReactEventHandler<HTMLImageElement>;
  imageIsLoading: boolean;
  imageRef: Ref<HTMLImageElement>;
  imageState: string;
} => {
  const [imageState, setImageState] = useState<ImageState>(
    "loading-from-bucket"
  );
  const imageRef = useRef<HTMLImageElement>(null);
  const localFileImageSrc = useLocalFileImageSrc(cardDocument, setImageState);

  const imageIsLoading =
    imageState === "loading-from-bucket" ||
    imageState === "loading-from-fallback" ||
    imageState === "loading-from-local-file";

  /**
   * Ensure that the small thumbnail fades in each time the selected image changes.
   * Next.js seems to not fire `onLoad` when opening a page with a cached image.
   * This implementation was retrieved from https://stackoverflow.com/a/59809184
   */
  useEffect(() => {
    setImageState(
      imageRef.current == null || !imageRef.current.complete
        ? "loading-from-bucket"
        : "loaded-from-bucket"
    );
  }, [cardDocument.identifier]);

  const onLoad: React.ReactEventHandler<HTMLImageElement> = () => {
    if (imageState === "loading-from-bucket") {
      setImageState("loaded-from-bucket");
    } else if (imageState === "loading-from-fallback") {
      setImageState("loaded-from-fallback");
    } else if (imageState === "loading-from-local-file") {
      setImageState("loaded-from-local-file");
    }
  };

  // attempt to load directly from bucket first
  const thumbnailBucketURL = getBucketImageURL(
    cardDocument,
    small ? "small" : "large"
  );
  const imageBucketURLValid = thumbnailBucketURL !== undefined;
  const loadFromBucket =
    imageBucketURLValid &&
    (imageState === "loading-from-bucket" ||
      imageState === "loaded-from-bucket");

  const onError: React.ReactEventHandler<HTMLImageElement> = (img) => {
    img.preventDefault();
    img.currentTarget.onerror = null;
    setImageState((value) => {
      // The "bucket" tier only really exists as a distinct retry step when there's an actual
      // second URL to fall back to (imageBucketURLValid) - a card with no bucket configured
      // (orphans always; also AWS S3/dev-without-bucket-configured cards) is ALREADY loading
      // its one and only "fallback" URL from the very first render, just still labelled
      // "loading-from-bucket" because that's this hook's fixed initial state. Without this
      // check, a failure here would relabel to "loading-from-fallback" and re-render with the
      // exact same src string, which browsers don't re-fetch - the image would stay broken
      // forever with the spinner never resolving to the "Image unavailable" placeholder. See
      // docs/features/foreign-order-resilience.md for the orphan case this was written for.
      if (value === "loading-from-bucket" || value === "loaded-from-bucket") {
        return imageBucketURLValid ? "loading-from-fallback" : "errored";
      }
      return "errored";
    });
  };

  if (localFileImageSrc !== undefined) {
    return {
      imageSrc: localFileImageSrc,
      onLoad,
      onError,
      imageIsLoading,
      imageRef,
      imageState,
    };
  }

  // if image is unavailable in bucket, fall back on loading from worker if possible
  const imageWorkerURL = getWorkerImageURL(
    cardDocument,
    small ? "small" : "large"
  );
  const imageWorkerURLValid = imageWorkerURL !== undefined;
  const smallThumbnailURL = imageWorkerURLValid
    ? imageWorkerURL
    : cardDocument?.smallThumbnailUrl;
  const mediumThumbnailURL = imageWorkerURLValid
    ? imageWorkerURL
    : cardDocument?.mediumThumbnailUrl;

  const thumbnailFallbackURL = small ? smallThumbnailURL : mediumThumbnailURL;
  const imageSrc =
    loadFromBucket && !!thumbnailBucketURL
      ? thumbnailBucketURL
      : thumbnailFallbackURL;

  return {
    imageSrc,
    onLoad,
    onError,
    imageIsLoading,
    imageRef,
    imageState,
  };
};

interface CardImageProps {
  cardDocument: CardDocument;
  hidden: boolean;
  small: boolean;
  showDetailedViewOnClick: boolean;
  /** The `SearchQuery` specified when searching for this card - used to detect whether
   * `cardDocument` was matched to a specific printing via community tags. */
  searchQuery?: SearchQuery | undefined;
  /** Hints this specific image as the page's LCP element (next/image's `priority` prop) -
   * defaults to false, since almost every render of this shared component is one of many
   * cards in a grid, where eager-loading every image would be actively harmful. Only ever
   * pass true for a genuinely above-the-fold, singular hero-style usage. */
  priority?: boolean;
}

function CardImage({
  cardDocument, // cardDocument reference *must* be stable at call site for memoization to work!
  hidden,
  small,
  showDetailedViewOnClick,
  searchQuery,
  priority = false,
}: CardImageProps) {
  const dispatch = useAppDispatch();
  // Foreign-order resilience Phase 1 (issue #324): orphans get no version picker, tags, or
  // consensus surfaces - the detailed-view modal exposes exactly those (printing tags,
  // reporting), so clicking an orphan's image is a no-op rather than opening it.
  const canShowDetailedView = showDetailedViewOnClick && !cardDocument.isOrphan;
  const handleShowDetailedView = () => {
    if (canShowDetailedView) {
      dispatch(showCardDetailedViewModal({ card: cardDocument }));
    }
  };

  const { imageSrc, onLoad, onError, imageIsLoading, imageRef, imageState } =
    useImageSrc(cardDocument, small);

  // a few other computed constants
  const imageAlt = cardDocument.name ?? "Unnamed Card";
  const showSpinner = imageIsLoading && !hidden;

  const [showSlowLoadHint, setShowSlowLoadHint] = useState<boolean>(false);
  useEffect(() => {
    if (!showSpinner) {
      setShowSlowLoadHint(false);
      return;
    }
    const timer = setTimeout(
      () => setShowSlowLoadHint(true),
      SlowLoadHintDelayMS
    );
    return () => clearTimeout(timer);
  }, [showSpinner, cardDocument.identifier]);

  const isFavorite = useAppSelector((state: RootState) =>
    selectIsFavoriteRender(
      state,
      cardDocument?.searchq ?? "",
      cardDocument?.identifier ?? ""
    )
  );

  const printingMatchLabel = getPrintingMatchLabel(
    searchQuery,
    cardDocument.canonicalCard,
    cardDocument.printingTagStatus
  );

  //# endregion

  return (
    <>
      {showSpinner && (
        <>
          <Spinner zIndex={2} />
          {showSlowLoadHint && (
            <SlowLoadHint data-testid="card-image-slow-load-hint">
              Still loading&hellip;
            </SlowLoadHint>
          )}
        </>
      )}
      {imageSrc != null &&
        (hidden ? (
          <HiddenImage
            ref={imageRef}
            className="card-img"
            loading={priority ? undefined : "lazy"}
            priority={priority}
            src={imageSrc}
            onLoad={onLoad}
            onErrorCapture={onError}
            alt={imageAlt}
            fill={true}
            // Orphan images are fetched direct from Google, never our own CDN - owner ruling
            // (2026-07-22 security review) accepts the fetch itself remaining a signal to the
            // file's owner on author-only surfaces, but still asks for no-referrer so we're not
            // additionally leaking this site's own URL to Google on every request.
            referrerPolicy={cardDocument.isOrphan ? "no-referrer" : undefined}
          />
        ) : (
          <>
            {imageState === "errored" ? (
              <ErrorPlaceholder data-testid="card-image-error-placeholder">
                <i className="bi bi-exclamation-triangle" aria-hidden="true" />
                <span>Image unavailable</span>
              </ErrorPlaceholder>
            ) : (
              <>
                {cardDocument.isOrphan && (
                  <OrphanBadge data-testid="orphan-badge">
                    {cardDocument.sourceName}
                  </OrphanBadge>
                )}
                {isFavorite && small && (
                  <CardIcon bootstrapIconName="heart-fill" />
                )}
                {printingMatchLabel != null && small && (
                  <OverlayTrigger
                    placement="top"
                    overlay={
                      <Tooltip id={`printing-match-${cardDocument.identifier}`}>
                        {printingMatchLabel}
                      </Tooltip>
                    }
                  >
                    <MatchIndicatorIcon
                      data-testid="printing-match-indicator"
                      bootstrapIconName="patch-check-fill"
                    />
                  </OverlayTrigger>
                )}
                <VisibleImage
                  ref={imageRef}
                  className="card-img card-img-fade-in"
                  loading={priority ? undefined : "lazy"}
                  priority={priority}
                  imageIsLoading={imageIsLoading}
                  showDetailedViewOnClick={canShowDetailedView}
                  src={imageSrc}
                  onLoad={onLoad}
                  onErrorCapture={onError}
                  onClick={handleShowDetailedView}
                  alt={imageAlt}
                  fill={true}
                  referrerPolicy={
                    cardDocument.isOrphan ? "no-referrer" : undefined
                  }
                />
              </>
            )}
          </>
        ))}
    </>
  );
}

export const MemoizedCardImage = memo(CardImage);

interface CardProportionWrapperProps {
  small: boolean;
  bordered?: boolean;
}

const CardProportionWrapperStyle = styled.div<{ $borderWidth?: number }>`
  z-index: 0;
  background: var(--bs-secondary);
  border: solid ${(props) => props.$borderWidth ?? 0}px black;
`;

function CardProportionWrapper({
  small,
  bordered = false,
  children,
}: PropsWithChildren<CardProportionWrapperProps>) {
  return (
    <CardProportionWrapperStyle
      $borderWidth={bordered ? 2 : 0}
      className={`rounded-${small ? "lg" : "xl"} shadow-lg ratio ratio-7x5`}
    >
      {children}
    </CardProportionWrapperStyle>
  );
}

export const MemoizedCardProportionWrapper = memo(CardProportionWrapper);

interface CardProps {
  /** The card image identifier to display. */
  maybeCardDocument: CardDocument | undefined;
  /** If this `Card` is part of a gallery, use this prop to cache the previous image for visual smoothness. */
  maybePreviousCardDocument?: CardDocument | undefined;
  /** If this `Card` is part of a gallery, use this prop to cache the next image for visual smoothness. */
  maybeNextCardDocument?: CardDocument | undefined;
  /** The string to display in the `Card` header. */
  cardHeaderTitle: string;
  /** An element (intended for use with a series of buttons) to include in the `Card` header.  */
  cardHeaderButtons?: ReactElement;
  /** An element (e.g. prev/next buttons) to display in the card footer. If not passed, no footer will be rendered. */
  cardFooter?: ReactElement;
  /** A callback function for when the `Card` (the HTML surrounding the image) is clicked. */
  cardOnClick?: React.MouseEventHandler<HTMLElement>;
  /** A callback function for when the card name is clicked. */
  nameOnClick?: React.MouseEventHandler<HTMLElement>;
  /** The `SearchQuery` specified when searching for this card. */
  searchQuery?: SearchQuery | undefined;
  /** Whether no search results were found when searching for `searchQuery` under the configured search settings. */
  noResultsFound: boolean;
  /** Whether to highlight this card by showing a glowing border around it. */
  highlight?: boolean;
  /** When true, suppresses the card header and footer, showing only the image. */
  compressed?: boolean;
  /** Ref to attach to the card header for use as a drag handle. */
  handleRef?: (element: Element | null) => void;
}

const deduplicateCards = (
  cardDocuments: Array<CardDocument | undefined>
): Array<CardDocument> => {
  const ids = new Set();
  return cardDocuments.filter(
    (cardDocument) =>
      cardDocument !== undefined &&
      !ids.has(cardDocument.identifier) &&
      ids.add(cardDocument.identifier)
  ) as Array<CardDocument>;
};

/**
 * This component enables displaying cards with auxiliary information in a flexible, consistent way.
 */
export function Card({
  // CardDocument references must be stable for memoization to work!
  maybeCardDocument,
  maybePreviousCardDocument,
  maybeNextCardDocument,
  cardHeaderTitle,
  cardHeaderButtons,
  cardFooter,
  cardOnClick,
  nameOnClick,
  searchQuery,
  noResultsFound,
  highlight,
  compressed = false,
  handleRef,
}: CardProps) {
  //# region computed constants

  const cardImageElements =
    maybeCardDocument != null ? (
      <>
        {deduplicateCards([
          maybeCardDocument,
          maybePreviousCardDocument,
          maybeNextCardDocument,
        ]).map(
          (cardDocument) =>
            cardDocument !== undefined && (
              <MemoizedCardImage
                key={cardDocument.identifier}
                cardDocument={cardDocument}
                hidden={
                  cardDocument?.identifier !== maybeCardDocument.identifier
                }
                small={true}
                showDetailedViewOnClick={
                  cardDocument?.identifier === maybeCardDocument.identifier &&
                  cardOnClick == null
                }
                searchQuery={searchQuery}
              />
            )
        )}
      </>
    ) : noResultsFound ? (
      <Image
        className="card-img card-img-fade-in"
        loading="lazy"
        style={{ zIndex: 1 }}
        src="/blank.png"
        alt="Card not found"
        fill={true}
      />
    ) : (
      <Spinner />
    );

  // @ts-ignore // TODO
  const BSCardSubtitle: typeof BSCard.Subtitle =
    nameOnClick != null ? OutlinedBSCardSubtitle : BSCard.Subtitle;

  // BSCard renders a plain, non-interactive <div> - clicking it (via cardOnClick, e.g. to
  // select this card's image) was previously mouse-only, with no way to reach it by Tab or
  // activate it with Enter/Space. Only made focusable/keyboard-activatable when it's actually
  // clickable - a card with no cardOnClick (e.g. the What's New page) shouldn't pretend to be
  // a button. The single real cardOnClick call site (CardResultSet.tsx) ignores its event
  // argument entirely, so re-invoking it from a keydown handler is safe.
  const handleKeyDown = (event: React.KeyboardEvent<HTMLElement>) => {
    if (cardOnClick == null) {
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      cardOnClick(event as unknown as React.MouseEvent<HTMLElement>);
    }
  };

  //# endregion

  return (
    <BSCard
      className={`mpccard ${highlight ? "mpccard-highlight" : "mpccard-hover"}`}
      onClick={cardOnClick}
      onKeyDown={cardOnClick != null ? handleKeyDown : undefined}
      tabIndex={cardOnClick != null ? 0 : undefined}
      role={cardOnClick != null ? "button" : undefined}
      style={{ contentVisibility: "auto" }}
      {...getCardDataAttributes(maybeCardDocument)}
    >
      {!compressed && (
        <BSCard.Header
          ref={handleRef as React.Ref<HTMLDivElement>}
          className="pb-0 text-center"
          style={{ cursor: handleRef ? "grab" : undefined }}
        >
          <p className="mpccard-slot">{cardHeaderTitle}</p>
          {cardHeaderButtons}
        </BSCard.Header>
      )}
      <div>
        <MemoizedCardProportionWrapper small={true}>
          {cardImageElements}
        </MemoizedCardProportionWrapper>
        {!compressed && (
          <BSCard.Body className="mb-0 text-center">
            <BSCardSubtitle className="mpccard-name" onClick={nameOnClick}>
              {maybeCardDocument != null && maybeCardDocument.name}
              {maybeCardDocument == null &&
                searchQuery != undefined &&
                searchQuery.query}
            </BSCardSubtitle>
            <div className="mpccard-spacing">
              <BSCard.Text className="mpccard-source">
                {maybeCardDocument != null &&
                  // An orphan's dpi/sourceName are placeholders (issue #324's synthesized
                  // CardDocument, never fetched from anywhere) - showing "[0 DPI]" would read as
                  // real catalog data we don't actually have.
                  (maybeCardDocument.isOrphan
                    ? maybeCardDocument.sourceName
                    : `${maybeCardDocument.sourceName} [${maybeCardDocument.dpi} DPI]`)}
                {maybeCardDocument == null &&
                  searchQuery != undefined &&
                  "Your search query"}
              </BSCard.Text>
            </div>
          </BSCard.Body>
        )}
      </div>
      {!compressed && cardFooter != null && (
        <BSCard.Footer
          className="padding-top"
          style={{ paddingTop: 50 + "px" }}
        >
          {cardFooter}
        </BSCard.Footer>
      )}
    </BSCard>
  );
}

export const MemoizedCard = memo(Card);

interface EditorCardProps {
  /** The card image identifier to display. */
  imageIdentifier: string | undefined;
  /** If this `Card` is part of a gallery, use this prop to cache the previous image for visual smoothness. */
  previousImageIdentifier?: string | undefined;
  /** If this `Card` is part of a gallery, use this prop to cache the next image for visual smoothness. */
  nextImageIdentifier?: string | undefined;
  /** The string to display in the `Card` header. */
  cardHeaderTitle: string;
  /** An element (intended for use with a series of buttons) to include in the `Card` header.  */
  cardHeaderButtons?: ReactElement;
  /** An element (e.g. prev/next buttons) to display in the card footer. If not passed, no footer will be rendered. */
  cardFooter?: ReactElement;
  /** A callback function for when the `Card` (the HTML surrounding the image) is clicked. */
  cardOnClick?: React.MouseEventHandler<HTMLElement>;
  /** A callback function for when the card name is clicked. */
  nameOnClick?: React.MouseEventHandler<HTMLElement>;
  /** The `SearchQuery` specified when searching for this card. */
  searchQuery?: SearchQuery | undefined;
  /** Whether no search results were found when searching for `searchQuery` under the configured search settings. */
  noResultsFound: boolean;
  /** Whether to highlight this card by showing a glowing border around it. */
  highlight?: boolean;
  /** When true, suppresses the card header and footer, showing only the image. */
  compressed?: boolean;
  /** Ref to attach to the card header for use as a drag handle. */
  handleRef?: (element: Element | null) => void;
}

/**
 * This component is a thin layer on top of `Card` that retrieves `CardDocument` items by their identifiers
 * from the Redux store (used in the project editor).
 * We have this layer because search results are returned as a list of image identifiers
 * (to minimise the quantity of data stored in Elasticsearch), so the full `CardDocument` items must be looked up.
 */
export function EditorCard({
  imageIdentifier,
  previousImageIdentifier,
  nextImageIdentifier,
  cardHeaderTitle,
  cardHeaderButtons,
  cardFooter,
  cardOnClick,
  nameOnClick,
  searchQuery,
  noResultsFound,
  highlight,
  compressed,
  handleRef,
}: EditorCardProps) {
  //# region queries and hooks

  const maybeCardDocument = useAppSelector((state: RootState) =>
    selectCardDocumentByIdentifier(state, imageIdentifier)
  );
  const maybePreviousCardDocument = useAppSelector((state: RootState) =>
    selectCardDocumentByIdentifier(state, previousImageIdentifier)
  );
  const maybeNextCardDocument = useAppSelector((state: RootState) =>
    selectCardDocumentByIdentifier(state, nextImageIdentifier)
  );

  //# endregion

  return (
    <MemoizedCard
      maybeCardDocument={maybeCardDocument}
      maybePreviousCardDocument={maybePreviousCardDocument}
      maybeNextCardDocument={maybeNextCardDocument}
      cardHeaderTitle={cardHeaderTitle}
      cardHeaderButtons={cardHeaderButtons}
      cardFooter={cardFooter}
      cardOnClick={cardOnClick}
      nameOnClick={nameOnClick}
      searchQuery={searchQuery}
      noResultsFound={noResultsFound}
      highlight={highlight}
      compressed={compressed}
      handleRef={handleRef}
    />
  );
}

export const MemoizedEditorCard = memo(EditorCard);

interface DatedCardProps {
  cardDocument: CardDocument;
  headerDate: "created" | "modified";
  compressed?: boolean;
}
/**
 * This component is a thin layer on top of `Card` for use in the What's New page.
 */
export function DatedCard({
  cardDocument,
  headerDate = "created",
  compressed,
}: DatedCardProps) {
  return (
    <Col>
      <MemoizedCard
        key={`new-cards-${cardDocument.identifier}`}
        maybeCardDocument={cardDocument}
        cardHeaderTitle={
          headerDate === "created"
            ? cardDocument.dateCreated
            : cardDocument.dateModified
        }
        noResultsFound={false}
        compressed={compressed}
      />
    </Col>
  );
}
