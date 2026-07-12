import { Head, Html, Main, NextScript } from "next/document";

import { lato } from "@/pages/_app";

export default function Document() {
  return (
    <Html>
      <Head>
        {/* Keyrune MTG set-symbol icon font (SIL OFL 1.1) - copied into public/keyrune/
            at install time (see scripts/generate-keyrune-assets.js), gitignored, always
            matching whatever keyrune version is installed. Used by CanonicalCardFilter.tsx
            to show a set's icon inline with its printing filter row. */}
        <link rel="stylesheet" href="/keyrune/css/keyrune.min.css" />
      </Head>
      <body className={lato.className}>
        <Main />
        <NextScript />
      </body>
    </Html>
  );
}
