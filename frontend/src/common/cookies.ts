/**
 * Data API for interacting with anything stored in cookies or local storage.
 */

import Cookies from "js-cookie";

import {
  AnonymousIdKey,
  BackendURLKey,
  CSRFKey,
  FavoritesKey,
  ManualOverridesKey,
  PinnedSourcesKey,
  SearchSettingsKey,
} from "@/common/constants";
import { Convert } from "@/common/schema_types";
import {
  Project,
  SearchSettings,
  SourceDocuments,
  SourceRow,
} from "@/common/types";
import { getSourceRowsFromSourceSettings } from "@/common/utils";
import { ManualOverride } from "@/features/pdf/bleedNormalize";
import { FavoritesState } from "@/store/slices/favoritesSlice";
import { getDefaultSearchSettings } from "@/store/slices/searchSettingsSlice";

const MANUAL_OVERRIDE_VALUES: ReadonlyArray<ManualOverride> = [
  "auto",
  "force-bleed",
  "force-trimmed",
];

//# region CSRF
// TODO: unsure if we still need this.

export function getCSRFHeader(): HeadersInit | undefined {
  const csrfToken = Cookies.get(CSRFKey);
  if (csrfToken != null) {
    return { "X-CSRFToken": csrfToken };
  }
  return undefined;
}

//# endregion

//# region search settings

/**
 * Get search settings from localStorage data. If valid data is retrieved,
 * ensure that all `sourceDocuments` are included in the returned settings,
 * with any new sources that weren't previously included added to the end and enabled.
 */
export function getLocalStorageSearchSettings(
  sourceDocuments: SourceDocuments
): SearchSettings {
  const serialisedRawSettings = localStorage.getItem(SearchSettingsKey) ?? "{}";
  try {
    const searchSettings = Convert.toSearchSettings(serialisedRawSettings);
    // great, the user has valid search settings stored in their browser local storage.
    // reconcile against sourceDocuments
    const sourceInDatabaseSet: Set<number> = new Set(
      Object.values(sourceDocuments).map((sourceDocument) =>
        parseInt(sourceDocument.pk)
      )
    );
    // types have to be narrowed here because quicktype doesn't support our SourceRow data structure :(
    const sources: Array<SourceRow> = getSourceRowsFromSourceSettings(
      searchSettings.sourceSettings
    );
    const sourceInLocalStorageSet: Set<number> = new Set(
      sources.map((row) => row[0])
    );
    // one fat line of reconciliation, good luck reading this future nick! i wrote this at 12:26am.
    searchSettings.sourceSettings.sources = sources
      .filter((row: SourceRow) => sourceInDatabaseSet.has(row[0]))
      .concat(
        Array.from(sourceInDatabaseSet)
          .filter((pk: number) => !sourceInLocalStorageSet.has(pk))
          .map((pk: number) => [pk, true])
      );
    return searchSettings;
  } catch (e) {
    // quicktype will throw an error if the user's stored settings do not match the schema
    // e.g. upon first page load
    // just return the default settings
    return getDefaultSearchSettings(sourceDocuments);
  }
}

export function setLocalStorageSearchSettings(settings: SearchSettings): void {
  localStorage.setItem(SearchSettingsKey, JSON.stringify(settings));
}

//# endregion

//# region favorites

/**
 * Get favorites from localStorage data.
 * Returns empty object if no valid data is found.
 */
export function getLocalStorageFavorites(): FavoritesState["favoriteRenders"] {
  const serialisedRawFavorites = localStorage.getItem(FavoritesKey);
  if (serialisedRawFavorites == null) {
    return {};
  }
  try {
    const parsed = JSON.parse(serialisedRawFavorites);
    // Validate that it's an object with string keys and array values
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      !Array.isArray(parsed)
    ) {
      // Validate all values are arrays of strings
      const isValid = Object.values(parsed).every(
        (value) =>
          Array.isArray(value) &&
          value.every((item) => typeof item === "string")
      );
      if (isValid) {
        return parsed as FavoritesState["favoriteRenders"];
      }
    }
    return {};
  } catch (e) {
    // Invalid JSON or structure, return empty object
    return {};
  }
}

export function setLocalStorageFavorites(
  favoriteRenders: FavoritesState["favoriteRenders"]
): void {
  localStorage.setItem(FavoritesKey, JSON.stringify(favoriteRenders));
}

//# endregion

//# region manual bleed overrides

/**
 * Get per-card PDF export bleed overrides from localStorage data (Proposal B PR-2, decision 4).
 * Returns empty object if no valid data is found.
 */
export function getLocalStorageManualOverrides(): Project["manualOverrides"] {
  const serialisedRawOverrides = localStorage.getItem(ManualOverridesKey);
  if (serialisedRawOverrides == null) {
    return {};
  }
  try {
    const parsed = JSON.parse(serialisedRawOverrides);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      !Array.isArray(parsed)
    ) {
      const isValid = Object.values(parsed).every((value) =>
        MANUAL_OVERRIDE_VALUES.includes(value as ManualOverride)
      );
      if (isValid) {
        return parsed as Project["manualOverrides"];
      }
    }
    return {};
  } catch (e) {
    // Invalid JSON or structure, return empty object
    return {};
  }
}

export function setLocalStorageManualOverrides(
  manualOverrides: Project["manualOverrides"]
): void {
  localStorage.setItem(ManualOverridesKey, JSON.stringify(manualOverrides));
}

//# endregion

//# region backend

export function getLocalStorageBackendURL() {
  return localStorage.getItem(BackendURLKey);
}

export function setLocalStorageBackendURL(url: string) {
  localStorage.setItem(BackendURLKey, url);
}

export function clearLocalStorageBackendURL(): void {
  localStorage.removeItem(BackendURLKey);
}

//# endregion

//# region /display left-rail pinned-favourite sources (#353 seam)

/**
 * Owner-directed 2026-07-23 ("implement the pin UI + localStorage persistence now"): which
 * source pks the visitor has starred in the left rail's Sources accordion, so the collapsed
 * summary can show a quick-glance favourites strip. Deliberately device-local, not account-tied -
 * the real "save these as my defaults" version is issue #353, a disabled seam in the accordion's
 * UI until that ships. See docs/features/display-left-rail.md for the full rationale (same
 * validated-JSON-with-fallback shape as `getLocalStorageFavorites` above).
 */
export function getLocalStoragePinnedSourcePks(): number[] {
  const serialised = localStorage.getItem(PinnedSourcesKey);
  if (serialised == null) {
    return [];
  }
  try {
    const parsed = JSON.parse(serialised);
    if (Array.isArray(parsed) && parsed.every((pk) => typeof pk === "number")) {
      return parsed as number[];
    }
    return [];
  } catch (e) {
    return [];
  }
}

export function setLocalStoragePinnedSourcePks(pks: number[]): void {
  localStorage.setItem(PinnedSourcesKey, JSON.stringify(pks));
}

//# endregion

//# region printing tags

/**
 * A persistent, anonymous, client-generated identifier - used to attribute printing-tag
 * votes to "the same visitor" for rate-limiting and one-vote-per-visitor purposes. Not a
 * real Django session: this frontend's fetch calls all use `credentials: "same-origin"`,
 * and frontend/backend are cross-origin, so a session cookie would never round-trip here.
 * Generated once and persisted in localStorage; a cleared/incognito browser just gets a new one.
 */
export function getOrCreateAnonymousId(): string {
  const existing = localStorage.getItem(AnonymousIdKey);
  if (existing != null) {
    return existing;
  }
  const generated = crypto.randomUUID();
  localStorage.setItem(AnonymousIdKey, generated);
  return generated;
}

//# endregion
