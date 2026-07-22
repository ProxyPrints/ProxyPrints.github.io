import styled from "@emotion/styled";
import { Queue } from "async-await-queue";
import React, { useEffect, useReducer } from "react";
import { PropsWithChildren } from "react";
import Container from "react-bootstrap/Container";
import { Provider } from "react-redux";

import { ContentMaxWidth } from "@/common/constants";
import {
  getLocalStorageFavorites,
  getLocalStorageManualOverrides,
} from "@/common/cookies";
import { useAppDispatch } from "@/common/types";
import { useChunkErrorRecovery } from "@/common/useChunkErrorRecovery";
import { useNavbarHeight } from "@/common/useNavbarHeight";
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

// `top`/`height` are driven by useNavbarHeight() (issue #250) rather than the static
// NavbarHeight constant - a real, measured value rather than a guess that regularly
// undercounts the navbar's actual rendered height (confirmed 64-88px vs the constant's 50px
// once enough nav links are visible/wrapped - see docs/troubleshooting.md). Getting this wrong
// isn't just a cosmetic few-px overlap: it's this container's own top-of-content offset, so an
// undercount hides that many pixels of every page's own top content behind the real fixed
// navbar (confirmed live on both /whatsthat's hero title and /display's toolbar - see
// docs/features/printing-tags.md's questionFeed section). Emotion's `css`-prop-style dynamic
// interpolation (a function of props) re-renders this rule whenever the measured height
// changes, same as any other prop-driven styled-component.
const ContentContainer = styled(Container, {
  // Container is react-bootstrap's own component, not a native element - emotion only auto-
  // filters non-DOM props for native `styled.div`-style tags (via @emotion/is-prop-valid), so a
  // custom prop on a wrapped third-party component gets forwarded all the way down to the
  // underlying <div> unless told not to (the same "React does not recognize the X prop" fix
  // MaxWidthContainer below already needs for its own `fullWidth`).
  shouldForwardProp: (prop) => prop !== "$navbarHeight",
})<{ $navbarHeight: number }>`
  overflow-y: scroll;
  overflow-x: hidden;
  top: ${(props) => props.$navbarHeight}px;
  position: fixed;
  height: calc(
    100vh - ${(props) => props.$navbarHeight}px
  ); // for compatibility with older browsers
  height: calc(
    100dvh - ${(props) => props.$navbarHeight}px
  ); // handles the ios address bar
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
  const navbarHeight = useNavbarHeight();
  return (
    <ContentContainer
      fluid
      className={`g-${gutter}`}
      $navbarHeight={navbarHeight}
      data-testid="content-container"
    >
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
