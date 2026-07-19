import styled from "@emotion/styled";
import fs from "fs";
import { GetStaticPaths, GetStaticProps } from "next";
import Head from "next/head";
import path from "path";

import { ProjectName } from "@/common/constants";
import Footer from "@/features/ui/Footer";
import { ProjectContainer } from "@/features/ui/Layout";

// Build-time-only site pages sourced from docs/, per
// docs/proposals/proposal-i-docs-as-site-source.md §1(a). Content is
// pre-rendered to HTML by ../../../scripts/generate-docs-site.js (an npm
// "prebuild" step, see package.json) into
// src/common/generated/docsSite/*.json, and injected here the same way
// about.tsx already injects backend-provided HTML: dangerouslySetInnerHTML
// on build-time-trusted content, not user input.

interface GuidePageProps {
  title: string;
  html: string;
  sourcePath: string;
}

interface ManifestEntry {
  sitePath: string;
  slug: string;
  title: string;
  sourcePath: string;
}

const docsSiteDir = path.join(
  process.cwd(),
  "src",
  "common",
  "generated",
  "docsSite"
);

function readManifest(): ManifestEntry[] {
  const manifestPath = path.join(docsSiteDir, "manifest.json");
  if (!fs.existsSync(manifestPath)) {
    // generate-docs-site.js hasn't run (e.g. a `next dev` invocation that
    // skipped `npm run build`'s prebuild step) - render nothing rather
    // than crashing the whole dev server.
    return [];
  }
  return JSON.parse(fs.readFileSync(manifestPath, "utf-8"));
}

export const getStaticPaths: GetStaticPaths = async () => {
  const manifest = readManifest();
  return {
    paths: manifest.map((entry) => ({
      params: { slug: entry.slug === "index" ? [] : entry.slug.split("__") },
    })),
    fallback: false,
  };
};

export const getStaticProps: GetStaticProps<GuidePageProps> = async ({
  params,
}) => {
  const slugParts = (params?.slug as string[] | undefined) ?? [];
  const slug = slugParts.length === 0 ? "index" : slugParts.join("__");
  const entryPath = path.join(docsSiteDir, `${slug}.json`);
  if (!fs.existsSync(entryPath)) {
    return { notFound: true };
  }
  const { title, html, sourcePath } = JSON.parse(
    fs.readFileSync(entryPath, "utf-8")
  );
  return { props: { title, html, sourcePath } };
};

const GuideContent = styled.div`
  h1:first-of-type {
    margin-top: 0;
  }
`;

const SourceNote = styled.p`
  opacity: 0.7;
  font-size: 0.9em;
`;

export default function GuidePage({ title, html, sourcePath }: GuidePageProps) {
  return (
    <ProjectContainer>
      <Head>
        <title>{`${title} — ${ProjectName} Guide`}</title>
        <meta name="description" content={`${title} — ${ProjectName} Guide`} />
      </Head>
      <GuideContent dangerouslySetInnerHTML={{ __html: html }} />
      <SourceNote>
        Source:{" "}
        <a
          href={`https://github.com/ProxyPrints/ProxyPrints.github.io/blob/master/${sourcePath}`}
          target="_blank"
        >
          {sourcePath}
        </a>
        . This page is generated at build time from that file — edits happen
        there, not here.
      </SourceNote>
      <Footer />
    </ProjectContainer>
  );
}
