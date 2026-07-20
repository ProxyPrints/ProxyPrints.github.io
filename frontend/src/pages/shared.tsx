import Head from "next/head";
import React from "react";

import { ProjectName } from "@/common/constants";
import { NoBackendDefault } from "@/components/NoBackendDefault";
import { SharedDeckPage } from "@/features/savedDecks/SharedDeckPage";
import { ProjectContainer } from "@/features/ui/Layout";
import { useRemoteBackendConfigured } from "@/store/slices/backendSlice";

function SharedDeckOrDefault() {
  const remoteBackendConfigured = useRemoteBackendConfigured();
  return remoteBackendConfigured ? (
    <SharedDeckPage />
  ) : (
    <NoBackendDefault requirement="remote" />
  );
}

export default function Shared() {
  return (
    <ProjectContainer>
      <Head>
        <title>{`${ProjectName} Shared Deck`}</title>
        <meta
          name="description"
          content={`View a deck shared with you via ${ProjectName}.`}
        />
      </Head>
      <SharedDeckOrDefault />
    </ProjectContainer>
  );
}
