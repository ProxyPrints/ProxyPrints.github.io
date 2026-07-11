// pdfjs-dist ships an ESM worker script that Next's webpack config can't
// resolve via `new URL(..., import.meta.url)` (see the "ESM packages need to
// be imported" build error). Copying it into public/ and loading it as a
// plain static asset sidesteps that entirely. Runs on every install so it
// always matches whatever pdfjs-dist version is actually installed - the
// copy itself is gitignored, not committed.
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const dirname = path.dirname(fileURLToPath(import.meta.url));

const source = path.join(
  dirname,
  "..",
  "node_modules",
  "pdfjs-dist",
  "build",
  "pdf.worker.min.mjs"
);
const destination = path.join(dirname, "..", "public", "pdf.worker.min.mjs");

fs.copyFileSync(source, destination);
