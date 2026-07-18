import Head from "next/head";
import React from "react";

import { ProjectName } from "@/common/constants";
import { NoBackendDefault } from "@/components/NoBackendDefault";
import { MyDecksPage } from "@/features/savedDecks/MyDecksPage";
import Footer from "@/features/ui/Footer";
import { ProjectContainer } from "@/features/ui/Layout";
import {
  useProjectName,
  useRemoteBackendConfigured,
} from "@/store/slices/backendSlice";

function MyDecksOrDefault() {
  const remoteBackendConfigured = useRemoteBackendConfigured();
  return remoteBackendConfigured ? (
    <>
      <MyDecksPage />
      <Footer />
    </>
  ) : (
    <NoBackendDefault requirement="remote" />
  );
}

export default function MyDecks() {
  const projectName = useProjectName();
  return (
    <ProjectContainer>
      <Head>
        <title>{`${projectName} My Decks`}</title>
        <meta
          name="description"
          content={`View, load, and manage your saved decks in ${ProjectName}.`}
        />
      </Head>
      <MyDecksOrDefault />
    </ProjectContainer>
  );
}
