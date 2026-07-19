import styled from "@emotion/styled";
import { GetStaticPaths, GetStaticProps } from "next";
import Head from "next/head";

import { ProjectName } from "@/common/constants";
import {
  readGeneratedPage,
  readManifest,
  renderMarkdown,
} from "@/features/guide/docsSite";
import Footer from "@/features/ui/Footer";
import { ProjectContainer } from "@/features/ui/Layout";

// Build-time-only site pages sourced from docs/, per
// docs/proposals/proposal-i-docs-as-site-source.md's single-transform
// architecture: .github/scripts/publish_site.py (Python) owns ALL
// link-rewrite logic and writes pre-transformed markdown into
// frontend/generated-docs/*.json (gitignored, run via `npm run
// docs:generate` locally, or a dedicated step in
// .github/workflows/deploy-frontend.yml before `npm run build`). This
// page has no transform logic of its own - it only reads that markdown
// (via @/features/guide/docsSite, kept out of this file so its fs usage
// never leaks into the client bundle) and renders it to HTML via
// `marked`, then injects it the same way about.tsx already injects
// backend-provided HTML: dangerouslySetInnerHTML on build-time-trusted
// content, not user input.

interface GuidePageProps {
  title: string;
  html: string;
  sourcePath: string;
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
  const page = readGeneratedPage(slug);
  if (page === null) {
    return { notFound: true };
  }
  return {
    props: {
      title: page.title,
      html: renderMarkdown(page.markdown),
      sourcePath: page.sourcePath,
    },
  };
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
