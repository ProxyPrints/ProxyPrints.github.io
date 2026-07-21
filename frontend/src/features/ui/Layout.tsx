import styled from "@emotion/styled";
import { Queue } from "async-await-queue";
import React, { useEffect, useReducer } from "react";
import { PropsWithChildren } from "react";
import Container from "react-bootstrap/Container";
import { Provider } from "react-redux";

import { ContentMaxWidth, NavbarHeight } from "@/common/constants";
import {
  getLocalStorageFavorites,
  getLocalStorageManualOverrides,
} from "@/common/cookies";
import { useAppDispatch } from "@/common/types";
import { useChunkErrorRecovery } from "@/common/useChunkErrorRecovery";
import { useBackendSetter } from "@/features/backend/useBackendSetter";
import { ClientSearchContextProvider } from "@/features/clientSearch/clientSearchContext";
import { clientSearchService } from "@/features/clientSearch/clientSearchService";
import {
  DownloadContext,
  DownloadContextProvider,
} from "@/features/download/download";
import { Modals } from "@/features/modals/Modals";
import { pdfRenderService } from "@/features/pdf/pdfRenderService";
import { CryptoSessionProvider } from "@/features/savedDecks/cryptoSession";
import { Toasts } from "@/features/toasts/Toasts";
import ProjectNavbar from "@/features/ui/Navbar";
import { setAllFavoriteRenders } from "@/store/slices/favoritesSlice";
import { setAllManualOverrides } from "@/store/slices/projectSlice";
import store from "@/store/store";

const OverscrollProvider = styled(Provider)`
  overscroll-behavior: none;
  overflow-x: hidden;
  overflow-y: hidden; // https://stackoverflow.com/a/69589919/13021511
`;

const ContentContainer = styled(Container)`
  overflow-y: scroll;
  overflow-x: hidden;
  top: ${NavbarHeight}px;
  position: fixed;
  height: calc(
    100vh - ${NavbarHeight}px
  ); // for compatibility with older browsers
  height: calc(100dvh - ${NavbarHeight}px); // handles the ios address bar
`;

interface MaxWidthContainerProps {
  fullWidth?: boolean;
}

// Issue #287 - `fullWidth` is an additive, optional escape hatch from the app-wide
// `ContentMaxWidth` cap (default `false`/unset, i.e. every existing caller's behaviour is
// unchanged). Container isn't a native DOM tag, so Emotion forwards every prop to it by default
// (including this component-only one) unless told not to - shouldForwardProp keeps `fullWidth`
// stopping at this boundary rather than leaking onto the underlying `<div>` (same
// "React does not recognize the X prop" fix OverflowCol.tsx already uses for its own style-only
// props). When true, the max-width override is removed entirely (not swapped for some other fixed
// value) - `fluid` is passed straight through to react-bootstrap's `Container` alongside it so its
// own default (non-fluid) breakpoint max-widths don't reassert themselves once our override is
// gone. See this prop's own call site in display.tsx for why /display needs this: two
// 1200px-breakpoint-inline rails otherwise leave the sheet region only ~520px wide inside the cap,
// vs. ~720px uncapped - docs/proposals/proposal-h-display-layout-spec.md §7 conflict #3.
const MaxWidthContainer = styled(Container, {
  shouldForwardProp: (prop) => prop !== "fullWidth",
})<MaxWidthContainerProps>`
  max-width: ${(props) => (props.fullWidth ? "none" : `${ContentMaxWidth}px`)};
`;

interface ProjectContainerProps {
  gutter?: number;
  fullWidth?: boolean;
}

export function ProjectContainer({
  gutter = 2,
  fullWidth = false,
  children,
}: PropsWithChildren<ProjectContainerProps>) {
  return (
    <ContentContainer fluid className={`g-${gutter}`}>
      <MaxWidthContainer
        fluid={fullWidth}
        fullWidth={fullWidth}
        className={`g-${gutter}`}
      >
        {children}
      </MaxWidthContainer>
    </ContentContainer>
  );
}

export function LayoutWithoutReduxProvider({ children }: PropsWithChildren) {
  const downloadContext: DownloadContext = new Queue(10, 50);
  const [forceUpdateValue, forceUpdate] = useReducer((x: number) => x + 1, 0);
  useBackendSetter();
  useChunkErrorRecovery();
  const dispatch = useAppDispatch();

  /**
   * Initialise local files service webworker andoad favourites on app init.
   */
  useEffect(() => {
    const favorites = getLocalStorageFavorites();
    if (Object.keys(favorites).length > 0) {
      dispatch(setAllFavoriteRenders(favorites));
    }
    const manualOverrides = getLocalStorageManualOverrides();
    if (Object.keys(manualOverrides).length > 0) {
      dispatch(setAllManualOverrides(manualOverrides));
    }
    clientSearchService.initialiseWorker();
    pdfRenderService.initialiseWorker();
  }, []);

  return (
    <DownloadContextProvider value={downloadContext}>
      <ClientSearchContextProvider
        value={{ clientSearchService, forceUpdate, forceUpdateValue }}
      >
        <CryptoSessionProvider>
          <Toasts />
          <Modals />
          <ProjectNavbar />
          {children}
        </CryptoSessionProvider>
      </ClientSearchContextProvider>
    </DownloadContextProvider>
  );
}

export default function Layout({ children }: PropsWithChildren) {
  return (
    <OverscrollProvider store={store}>
      <LayoutWithoutReduxProvider>{children}</LayoutWithoutReduxProvider>
    </OverscrollProvider>
  );
}
