// Keyrune (MTG set-symbol icon font, SIL OFL 1.1 licensed for the font files themselves -
// see node_modules/keyrune/LICENSE.md) ships as a webfont + CSS meant to be served as static
// files, which Next's static export can't pull directly out of node_modules at request time -
// same problem copy-pdf-worker.js solves for pdfjs-dist. This copies the font + CSS into
// public/keyrune/ (preserving keyrune's own css/ and fonts/ sibling layout, since keyrune.css's
// @font-face rules reference the font files with relative "../fonts/..." URLs), and also
// extracts a set-code -> Keyrune private-use-area codepoint mapping into a small generated JSON
// module, so CanonicalCardFilter.tsx can render a set's icon by embedding that codepoint
// character directly in a plain label string (see that file for why: the dropdown-tree-select
// library's label prop must stay a plain string, not JSX, to avoid breaking its search/tag
// rendering). Runs on every install so it always matches whatever keyrune version is actually
// installed - none of the output is committed.

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const dirname = path.dirname(fileURLToPath(import.meta.url));
const keyruneRoot = path.join(dirname, "..", "node_modules", "keyrune");

function copyDir(source, destination) {
  fs.mkdirSync(destination, { recursive: true });
  for (const entry of fs.readdirSync(source, { withFileTypes: true })) {
    const sourcePath = path.join(source, entry.name);
    const destinationPath = path.join(destination, entry.name);
    if (entry.isDirectory()) {
      copyDir(sourcePath, destinationPath);
    } else {
      fs.copyFileSync(sourcePath, destinationPath);
    }
  }
}

const publicKeyruneDir = path.join(dirname, "..", "public", "keyrune");
copyDir(path.join(keyruneRoot, "css"), path.join(publicKeyruneDir, "css"));
copyDir(path.join(keyruneRoot, "fonts"), path.join(publicKeyruneDir, "fonts"));

const css = fs.readFileSync(
  path.join(keyruneRoot, "css", "keyrune.css"),
  "utf-8"
);

const codepoints = {};
const defaultMatch = css.match(/\.ss:before\s*\{\s*content:\s*"\\([a-f0-9]+)"/);
if (defaultMatch == null) {
  throw new Error(
    "Could not find keyrune's default .ss:before codepoint - has the keyrune package's CSS structure changed?"
  );
}
codepoints.default = defaultMatch[1];

const setPattern = /\.ss-([a-z0-9]+):before\s*\{\s*content:\s*"\\([a-f0-9]+)"/g;
let match;
while ((match = setPattern.exec(css)) !== null) {
  const [, code, codepoint] = match;
  codepoints[code] = codepoint;
}

const generatedDir = path.join(dirname, "..", "src", "common", "generated");
fs.mkdirSync(generatedDir, { recursive: true });
fs.writeFileSync(
  path.join(generatedDir, "keyruneCodepoints.json"),
  JSON.stringify(codepoints)
);
