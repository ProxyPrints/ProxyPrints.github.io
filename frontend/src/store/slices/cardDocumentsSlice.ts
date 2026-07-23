/**
 * State management for cards retrieved from the backend.
 */

import { createSelector } from "@reduxjs/toolkit";

import { Back, CardEndpointPageSize, Front } from "@/common/constants";
import { buildOrphanCardDocuments } from "@/common/orphanCard";
import { CardType } from "@/common/schema_types";
import {
  CardDocument,
  CardDocumentsState,
  createAppAsyncThunk,
  createAppSlice,
  Faces,
  OramaCardDocument,
  useAppSelector,
} from "@/common/types";
import { CardDocuments } from "@/common/types";
import { ClientSearchService } from "@/features/clientSearch/clientSearchService";
import { APIGetCards } from "@/store/api";
import { fetchCardbacksAndReportError } from "@/store/slices/cardbackSlice";
import {
  selectProjectMemberIdentifiers,
  selectUniqueCardIdentifiers,
} from "@/store/slices/projectSlice";
import { fetchSearchResultsAndReportError } from "@/store/slices/searchResultsSlice";
import { setNotification } from "@/store/slices/toastsSlice";
import { AppDispatch, RootState } from "@/store/store";

/**
 * For every project member's selectedImage, remember the query text/cardType that slot
 * actually asked for - foreign-order resilience Phase 1 (issue #324) needs this so an orphan's
 * synthesized CardDocument (see buildOrphanCardDocuments below) can carry the user's own stand-in
 * name and the correct front/back-consistent card type, rather than a generic placeholder. First
 * slot to reference a given identifier wins if more than one slot happens to share it under
 * different query text - an edge case, not the common path.
 */
const buildStandInQueryByIdentifier = (
  projectMembers: RootState["project"]["members"]
): Map<string, { name: string | null; cardType: CardType }> => {
  const standInQueryByIdentifier = new Map<
    string,
    { name: string | null; cardType: CardType }
  >();
  for (const member of projectMembers) {
    for (const face of [Front, Back] as Array<Faces>) {
      const projectMemberAtFace = member[face];
      const identifier = projectMemberAtFace?.selectedImage;
      const query = projectMemberAtFace?.query;
      if (identifier != null && !standInQueryByIdentifier.has(identifier)) {
        standInQueryByIdentifier.set(identifier, {
          name: query?.query ?? null,
          cardType: query?.cardType ?? CardType.Card,
        });
      }
    }
  }
  return standInQueryByIdentifier;
};

//# region async thunk

const typePrefix = "cardDocuments/fetchCardDocuments";

export const getCardDocumentRequestPromiseChain = async (
  identifiersToSearch: Array<string>,
  backendURL: string | null
): Promise<CardDocuments> => {
  if (identifiersToSearch.length > 0 && backendURL != null) {
    // this block of code looks a bit arcane.
    // we're dynamically constructing a promise chain according to the number of requests we need to make
    // to retrieve all database rows corresponding to `identifiersToSearch`.
    // e.g. say that `identifiersToSearch` contains 1500 identifiers.
    // two requests will be issued, the first for 1000 cards, and the second for 500 cards
    // (with the second request only commencing once the first has finished).
    return Array.from(
      Array(Math.ceil(identifiersToSearch.length / CardEndpointPageSize)).keys()
    ).reduce(function (promiseChain: Promise<CardDocuments>, page: number) {
      return promiseChain.then(async function (previousValue: CardDocuments) {
        const cards = await APIGetCards(
          backendURL,
          identifiersToSearch.slice(
            page * CardEndpointPageSize,
            (page + 1) * CardEndpointPageSize
          )
        );
        return { ...previousValue, ...cards };
      });
    }, Promise.resolve({}));
  } else {
    return {};
  }
};

// Exported (not just via fetchCardDocumentsAndReportError below) so listenerMiddleware.ts can
// match on fetchCardDocuments.fulfilled directly - foreign-order resilience Phase 1 (issue
// #324) needs its own invalid-identifier listener to re-run once cardDocuments.cardDocuments
// actually reflects whether an identifier is a real catalog card, an orphan, or neither, which
// isn't settled yet by the time fetchSearchResults.fulfilled/fetchCardbacks.fulfilled (the
// listener's original triggers) fire - see that listener's own comment for the full ordering
// rationale.
export const fetchCardDocuments = createAppAsyncThunk(
  typePrefix,
  /**
   * This function queries card documents (entire database rows) from the backend. It only queries cards which have
   * not yet been queried.
   */
  async (
    arg: { refreshCardbacks?: boolean } | undefined,
    { dispatch, getState, extra }
  ) => {
    const { clientSearchService } = extra as {
      clientSearchService: ClientSearchService;
    };
    await fetchSearchResultsAndReportError(dispatch);
    if (arg?.refreshCardbacks || getState().cardbacks.cardbacks.length === 0) {
      await fetchCardbacksAndReportError(dispatch);
    }

    const state = getState() as RootState;

    // Union of the search-derived identifier set (the pre-existing source of truth) with every
    // raw selectedImage the project actually references, including ones the fork of the site's
    // search index never matched (see this thunk's own foreign-order-resilience comment below).
    // selectUniqueCardIdentifiers alone would never even attempt to resolve an orphan's
    // identifier, since by definition it never appears in any search result.
    const allIdentifiers = new Set([
      ...selectUniqueCardIdentifiers(state),
      ...selectProjectMemberIdentifiers(state),
    ]);
    const identifiersWithKnownData = new Set(
      Object.keys(state.cardDocuments.cardDocuments)
    );
    const identifiersToSearch = Array.from(
      new Set(
        Array.from(allIdentifiers).filter(
          (item) => !identifiersWithKnownData.has(item)
        )
      )
    );

    const backendURL = state.backend.url;
    const localResultsPromise: Promise<CardDocuments> =
      clientSearchService.getCardDocuments(identifiersToSearch);
    const remoteResultsPromise: Promise<CardDocuments> =
      backendURL != null
        ? getCardDocumentRequestPromiseChain(identifiersToSearch, backendURL)
        : new Promise(async (resolve) => resolve({}));
    return await Promise.all([localResultsPromise, remoteResultsPromise]).then(
      ([localResults, remoteResults]) => {
        const resolvedDocuments = { ...remoteResults, ...localResults };
        // Foreign-order resilience Phase 1 (issue #324): anything still unresolved after both
        // lookups, that also looks like a real Drive file ID, gets a synthesized orphan
        // CardDocument instead of being left out entirely - see common/orphanCard.ts's module
        // doc for the full rationale. Genuinely invalid identifiers (garbage, or a real
        // catalog ID whose source got disabled/removed) are unaffected - buildOrphanCardDocuments
        // only emits entries for identifiers that pass isLikelyDriveFileId, so anything else
        // stays exactly as absent as it always was, and listenerMiddleware.ts's existing
        // Invalid Cards flow still catches it.
        const stillUnresolved = identifiersToSearch.filter(
          (identifier) => resolvedDocuments[identifier] == null
        );
        const orphanDocuments =
          stillUnresolved.length > 0
            ? buildOrphanCardDocuments(
                stillUnresolved,
                buildStandInQueryByIdentifier(state.project.members)
              )
            : {};
        return { ...orphanDocuments, ...resolvedDocuments };
      }
    );
  }
);

export async function fetchCardDocumentsAndReportError(
  dispatch: AppDispatch,
  arg?: { refreshCardbacks?: boolean }
) {
  try {
    await dispatch(fetchCardDocuments(arg)).unwrap();
  } catch (error: any) {
    dispatch(
      setNotification([
        typePrefix,
        { name: error.name, message: error.message, level: "error" },
      ])
    );
    return null;
  }
}

//# endregion

//# region slice configuration

const initialState: CardDocumentsState = {
  cardDocuments: {},
  status: "idle",
  error: null,
};

export const cardDocumentsSlice = createAppSlice({
  name: "cardDocuments",
  initialState,
  reducers: {
    addCardDocuments: (state, action) => {
      state.cardDocuments = { ...state.cardDocuments, ...action.payload };
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchCardDocuments.pending, (state, action) => {
        state.status = "loading";
      })
      .addCase(fetchCardDocuments.fulfilled, (state, action) => {
        state.status = "succeeded";
        state.cardDocuments = { ...state.cardDocuments, ...action.payload };
      })
      .addCase(fetchCardDocuments.rejected, (state, action) => {
        state.status = "failed";
        state.error = {
          name: action.error.name ?? null,
          message: action.error.message ?? null,
          level: "error",
        };
      });
  },
});

export const { addCardDocuments } = cardDocumentsSlice.actions;
export default cardDocumentsSlice.reducer;

//# endregion

//# region selectors

export const selectCardDocumentByIdentifier = createSelector(
  (state: RootState, imageIdentifier: string | undefined) => imageIdentifier,
  (state: RootState, imageIdentifier: string | undefined) =>
    state.cardDocuments.cardDocuments,
  (imageIdentifier, cardDocuments) =>
    imageIdentifier != null ? cardDocuments[imageIdentifier] : undefined
);

export const selectCardDocumentsByIdentifiers = createSelector(
  (state: RootState, identifiers: Array<string>) => identifiers,
  (state: RootState, identifiers: Array<string>) =>
    state.cardDocuments.cardDocuments,
  // Explicit return type, not inferred: identifiers is every PROJECT MEMBER identifier, which
  // can include ones whose CardDocument hasn't been fetched into cardDocuments yet - without
  // this annotation, TypeScript (no noUncheckedIndexedAccess in this project's tsconfig) infers
  // `cardDocuments[identifier]` as always-CardDocument, silently hiding the real possibility of
  // `undefined` from every caller's type-checker. A guardless BleedOverrideSettings crashed on
  // exactly this (task #135); ExportImages.tsx had the same latent bug, unguarded, uncaught by
  // tsc for the same reason. See docs/lessons.md.
  (
    identifiers,
    cardDocuments
  ): { [identifier: string]: CardDocument | undefined } =>
    Object.fromEntries(
      identifiers.map((identifier) => [identifier, cardDocuments[identifier]])
    )
);

export const getCardSizesByIdentifier = (
  identifiers: Array<string>,
  cardDocuments: CardDocuments
) =>
  Object.fromEntries(
    identifiers.map((identifier) => [
      identifier,
      cardDocuments[identifier]?.size ?? 0,
    ])
  );

export const selectCardSizesByIdentifier = createSelector(
  (state: RootState, identifiers: Array<string>) => identifiers,
  (state: RootState, identifiers: Array<string>) =>
    state.cardDocuments.cardDocuments,
  getCardSizesByIdentifier
);

//# endregion

//# region hooks

export function useCardDocumentsByIdentifier(): {
  [identifier: string]: CardDocument | undefined;
} {
  const identifiers = Array.from(
    useAppSelector(selectProjectMemberIdentifiers)
  );
  return useAppSelector((state) =>
    selectCardDocumentsByIdentifiers(state, identifiers)
  );
}

//# endregion
