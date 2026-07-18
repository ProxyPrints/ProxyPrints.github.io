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

const MaxWidthContainer = styled(Container)`
  max-width: ${ContentMaxWidth}px;
`;

interface ProjectContainerProps {
  gutter?: number;
}

export function ProjectContainer({
  gutter = 2,
  children,
}: PropsWithChildren<ProjectContainerProps>) {
  return (
    <ContentContainer fluid className={`g-${gutter}`}>
      <MaxWidthContainer className={`g-${gutter}`}>
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
