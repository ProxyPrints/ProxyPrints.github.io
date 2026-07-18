import styled from "@emotion/styled";
import Head from "next/head";

import { MTGArtistConnection, ProjectName } from "@/common/constants";
import Footer from "@/features/ui/Footer";
import { ProjectContainer } from "@/features/ui/Layout";
import { useGetBackendInfoQuery } from "@/store/api";
import { useProjectName } from "@/store/slices/backendSlice";
const CentreAligned = styled.div`
  text-align: center;
`;

function BackendDescription() {
  const backendInfoQuery = useGetBackendInfoQuery();

  return (
    <>
      {backendInfoQuery.isSuccess &&
        backendInfoQuery.data?.name != null &&
        (backendInfoQuery.data?.description ?? "").length > 0 && (
          <>
            <h3>About {backendInfoQuery.data.name}</h3>
            <p
              dangerouslySetInnerHTML={{
                __html: backendInfoQuery.data.description ?? "",
              }}
            />
          </>
        )}
    </>
  );
}

export default function About() {
  const projectName = useProjectName();
  return (
    <ProjectContainer>
      <Head>
        <title>{`About ${projectName}`}</title>
        <meta name="description" content={`About ${projectName}`} />
      </Head>
      <h3>About {ProjectName}</h3>
      <p>
        {ProjectName} is an open source project licensed under the{" "}
        <a href="https://www.gnu.org/licenses/gpl-3.0.en.html" target="_blank">
          GNU General Public License 3
        </a>{" "}
        &mdash; meaning it is free to use, modify, and distribute. Read the
        license (linked) for more detail.
      </p>
      <p>
        This project is only possible because of the code contributions of the
        following people (thanks to{" "}
        <a href="https://contrib.rocks" target="_blank">
          contrib.rocks
        </a>{" "}
        for the graphic!):
      </p>
      <CentreAligned>
        <a
          href="https://github.com/chilli-axe/mpc-autofill/graphs/contributors"
          target="_blank"
        >
          <img
            src="https://contrib.rocks/image?repo=chilli-axe/mpc-autofill&columns=8"
            alt="Project contributors"
            style={{ maxWidth: 100 + "%" }}
          />
        </a>
      </CentreAligned>
      <BackendDescription />
      <p>
        Confirmed artist credits link out to{" "}
        <a href="https://www.mtgartistconnection.com" target="_blank">
          {MTGArtistConnection}
        </a>
        , a community-maintained directory of Magic: the Gathering artists -
        not affiliated with {ProjectName}. These links are built directly
        from the artist&apos;s name with no verification that a matching page
        exists; if you&apos;re an artist and want a richer, project-blessed
        way to link your own storefront, get in touch.
      </p>
      <h3>Disclaimer</h3>
      <p>
        Custom card images displayed on {ProjectName} are subject to the license
        terms under which they were uploaded to their hosts. {ProjectName} is
        not responsible for the content of user-uploaded images.
      </p>
      <p>
        {ProjectName} does not condone or support the resale (or other
        commercial use) of cards printed with this website in any way. Per your
        chosen print shop&apos;s user agreement, users acknowledge that they{" "}
        <i>
          &quot;...own all copyrights for [card images used in orders] or have
          full authorization to use them.&quot;
        </i>
      </p>
      <p>
        {ProjectName} is not affiliated with, produced by, or endorsed by any of
        the print shops listed on this site or any other commercial entities.
      </p>
      <h3 id="privacy-policy">Privacy Policy</h3>
      <b>Last updated: 12th July, 2026</b>
      <br />
      <br />
      <p>
        {ProjectName} does not use Google Analytics or any other
        visitor-tracking or analytics service. We use local storage to remember
        your search settings and your server configuration, which is considered
        core site functionality and cannot be disabled. No other usage data is
        collected by {ProjectName} itself.
      </p>
      <h4>Google Drive API</h4>
      <p>
        {ProjectName} offers an optional Google Drive integration that allows
        you to use Google Drive resources accessible to you as image sources.
        When you use this feature, {ProjectName} requests access to your Google
        Drive using the <code>drive.metadata.readonly</code> OAuth 2.0 scope.
        This grants the application read-only access to file metadata &mdash;
        specifically, the names, sizes, modification timestamps, and image
        dimensions of files in the Google Drive folders you explicitly select.{" "}
        {ProjectName} does not read file contents, create or modify any files,
        access files outside of folders you select, or access any other Google
        account data.
      </p>
      <p>
        <b>Data protection:</b> The OAuth access token issued by Google is held
        only in your browser&apos;s memory for the duration of the indexing
        session. It is never transmitted to {ProjectName}&apos;s servers, stored
        in local storage or cookies, or otherwise persisted. All communication
        with the Google Drive API occurs over HTTPS directly between your
        browser and Google.
      </p>
      <p>
        <b>Data retention and deletion:</b> {ProjectName} does not store any
        Google user data on its servers. The OAuth access token is discarded as
        soon as the indexing session completes, and is gone when you close or
        refresh the page. A temporary search index is built in your
        browser&apos;s memory from the file metadata retrieved during indexing;
        this index exists only for your current session and is not written to
        disk or local storage.
      </p>
      <p>
        {ProjectName}&apos;s use and transfer of information received from
        Google APIs to any other app will adhere to the{" "}
        <a
          href="https://developers.google.com/terms/api-services-user-data-policy"
          target="_blank"
        >
          Google API Services User Data Policy
        </a>
        , including the Limited Use requirements.
      </p>
      <Footer />
    </ProjectContainer>
  );
}
