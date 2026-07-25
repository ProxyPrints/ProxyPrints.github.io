import { Page } from "@playwright/test";

/**
 * Site-wide contrast/residual-grey audit tool (2026-07-25, owner-reported live-mobile defects on
 * /contributions and the editor's Print & Settings sheet). Mechanical companion to the "css-diff
 * harness pattern" other fidelity specs use (DisplayLeftRailFidelity.spec.ts,
 * CardbackPdfWaitFidelity.spec.ts) - extracts computed foreground/background pairs for every
 * text-owning DOM node in the current page and reports the WCAG contrast ratio against the
 * OWNER'S ratified bar (docs/features/theming.md's Verification section): AAA - 7:1 for normal
 * text, 4.5:1 for large/bold text (APCA is advisory-only, not computed here). Also flags any
 * background colour that is neither transparent nor a member of the Tokyo-11 palette
 * (TOKYO11_PALETTE below, kept in sync with _theme-tokens.scss by hand - see that file for the
 * canonical source) AND reads as "grey" (low saturation, not near-black/near-white) - the
 * "born grey" residual-Bootstrap-default signature docs/features/theming.md's theme-defaults
 * pass already documents one wave of.
 *
 * Usage: see tests/ContrastAudit.spec.ts for the runnable Playwright spec that exercises this
 * against the site's routes/states. To run standalone: `npx playwright test
 * tests/ContrastAudit.spec.ts --reporter=list` and read the console.log'd failure table (the
 * spec itself asserts zero failures, so it also works as an ordinary CI regression gate).
 *
 * KNOWN APPROXIMATIONS (documented rather than engineered away, given this is a triage tool, not
 * a pixel-exact renderer):
 *  - Ancestor `opacity` (e.g. Bootstrap's `.btn:disabled{opacity:.65}`) is folded in as an alpha
 *    multiplier on the FOREGROUND colour only, blended over the (undimmed) effective background.
 *    Real compositing would also dim any opaque background the disabled element itself painted;
 *    this under-dims that rare case (solid-fill disabled buttons; this codebase's disabled
 *    affordances are overwhelmingly outline/text style, where the own background is transparent
 *    and this approximation is exact).
 *  - No sub-pixel/gradient/box-shadow/backdrop-filter support - `background-color` and its alpha
 *    channel only.
 *  - Hover/focus states are NOT swept automatically for every node (real `:hover` needs a real
 *    mouse move per element, too expensive to do for every text node on every route) - callers
 *    that care about a specific control's hover/focus contrast should drive it explicitly (see
 *    the spec file's dedicated hover/focus cases for the four owner-reported controls).
 */

// Kept in sync BY HAND with frontend/src/styles/_theme-tokens.scss's colour section - see that
// file's own header comment for the ratified source of truth. Add a token here whenever that
// file gains one; this list intentionally does NOT include the runtime `--bs-*-bg-subtle`/
// `-text-emphasis` custom properties Bootstrap auto-generates, since those are exactly the class
// of value this audit exists to catch when they leak through unrouted.
export const TOKYO11_PALETTE_HEX = [
  "#1a1b26", // theme-body-bg / theme-btn-ink
  "#24283b", // theme-raised-bg
  "#2f3549", // theme-panel-bg
  "#2f3548", // theme-card-header-bg
  "#222234", // theme-band-bg
  "#16161e", // theme-divider
  "#c0caf5", // theme-text / theme-light
  "#a3aad0", // theme-muted
  "#ff9e64", // theme-primary
  "#e8935b", // theme-primary-hover (darken(#ff9e64, 8%), approx)
  "#9ece6a", // theme-success
  "#f7768e", // theme-danger
  "#e0af68", // theme-warning
  "#7dcfff", // theme-info
  "#bb9af7", // theme-accent
  "#4e5d6b", // AutofillCollapse's deliberately-preserved literal header token (owner ruling,
  // 2026-07-23 - see that component's own comment; distinct from theme-panel-bg by one hex
  // digit on purpose)
];

export interface ContrastFailure {
  selector: string;
  text: string;
  fg: string;
  bg: string;
  ratio: number;
  required: number;
  isLarge: boolean;
  isDisabled: boolean;
  reason: "contrast" | "off-palette-grey";
}

// Injected into the page via page.evaluate(collectInPage, args) - Playwright serialises the
// function via .toString() and runs it in-browser, so it must be self-contained (no closures
// over outer TS values/types - everything it needs comes in through `args`).
/* istanbul ignore next -- runs in-browser, not under node coverage */
function collectInPage(args: { palette: string[]; disabledFloor: number }) {
  const { palette, disabledFloor } = args;
  function parseColor(
    str: string
  ): { r: number; g: number; b: number; a: number } | null {
    const m = str.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const parts = m[1].split(",").map((s) => parseFloat(s.trim()));
    if (parts.length < 3 || parts.some((p) => Number.isNaN(p))) return null;
    return {
      r: parts[0],
      g: parts[1],
      b: parts[2],
      a: parts.length > 3 ? parts[3] : 1,
    };
  }

  function toHex(c: { r: number; g: number; b: number }): string {
    const h = (n: number) =>
      Math.round(Math.max(0, Math.min(255, n)))
        .toString(16)
        .padStart(2, "0");
    return `#${h(c.r)}${h(c.g)}${h(c.b)}`;
  }

  function blend(
    fg: { r: number; g: number; b: number; a: number },
    bg: { r: number; g: number; b: number }
  ) {
    const a = fg.a;
    return {
      r: fg.r * a + bg.r * (1 - a),
      g: fg.g * a + bg.g * (1 - a),
      b: fg.b * a + bg.b * (1 - a),
    };
  }

  function luminance(c: { r: number; g: number; b: number }): number {
    const [R, G, B] = [c.r, c.g, c.b].map((ch) => {
      const v = ch / 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * R + 0.7152 * G + 0.0722 * B;
  }

  function contrastRatio(
    fg: { r: number; g: number; b: number },
    bg: { r: number; g: number; b: number }
  ): number {
    const L1 = luminance(fg) + 0.05;
    const L2 = luminance(bg) + 0.05;
    return L1 > L2 ? L1 / L2 : L2 / L1;
  }

  function isGreyish(c: { r: number; g: number; b: number }): boolean {
    const max = Math.max(c.r, c.g, c.b);
    const min = Math.min(c.r, c.g, c.b);
    const lightness = (max + min) / 2 / 255;
    // low saturation, and not near-black/near-white (those are legitimate ink/paper extremes,
    // not "residual grey panel" territory)
    return max - min < 12 && lightness > 0.12 && lightness < 0.9;
  }

  function cumulativeOpacity(el: Element): number {
    let node: Element | null = el;
    let product = 1;
    while (node && node !== document.documentElement) {
      const op = parseFloat(getComputedStyle(node).opacity || "1");
      if (!Number.isNaN(op)) product *= op;
      node = node.parentElement;
    }
    return product;
  }

  function effectiveBackground(el: Element): {
    r: number;
    g: number;
    b: number;
  } {
    const layers: { r: number; g: number; b: number; a: number }[] = [];
    let node: Element | null = el;
    while (node) {
      const bg = parseColor(getComputedStyle(node).backgroundColor);
      if (bg && bg.a > 0) {
        layers.push(bg);
        if (bg.a >= 1) break; // fully opaque, nothing further back matters
      }
      node = node.parentElement;
    }
    // layers[0] is nearest (el itself); composite farthest-first onto an opaque white canvas
    let result = { r: 255, g: 255, b: 255 };
    for (let i = layers.length - 1; i >= 0; i--) {
      result = blend(layers[i], result);
    }
    return result;
  }

  function isLargeText(el: Element): boolean {
    const cs = getComputedStyle(el);
    const px = parseFloat(cs.fontSize);
    const weightRaw = cs.fontWeight;
    const weight =
      weightRaw === "bold"
        ? 700
        : weightRaw === "normal"
        ? 400
        : parseInt(weightRaw, 10) || 400;
    return px >= 24 || (px >= 18.66 && weight >= 700);
  }

  function shortSelector(el: Element): string {
    const testId = el.getAttribute("data-testid");
    const id = el.id;
    const cls = (el.getAttribute("class") || "")
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .join(".");
    const tag = el.tagName.toLowerCase();
    if (testId) return `${tag}[data-testid="${testId}"]`;
    if (id) return `${tag}#${id}`;
    if (cls) return `${tag}.${cls}`;
    return tag;
  }

  function isVisible(el: Element): boolean {
    // @ts-ignore checkVisibility is Chromium-only but this audit always runs under Chromium
    if (typeof (el as any).checkVisibility === "function") {
      // @ts-ignore
      return el.checkVisibility({
        checkOpacity: false,
        checkVisibilityCSS: true,
      });
    }
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  const paletteSet = new Set(palette.map((p) => p.toLowerCase()));
  const contrastFailures: any[] = [];
  const paletteFailures: any[] = [];
  const seenBgKeys = new Set<string>();

  const all = Array.from(document.querySelectorAll<HTMLElement>("*"));
  for (const el of all) {
    if (!isVisible(el)) continue;
    const hasDirectText = Array.from(el.childNodes).some(
      (n) => n.nodeType === 3 && (n.textContent || "").trim().length > 0
    );
    if (!hasDirectText) continue;

    const cs = getComputedStyle(el);
    const fgColor = parseColor(cs.color);
    if (!fgColor) continue;
    const bg = effectiveBackground(el);
    const opacity = cumulativeOpacity(el);
    // A fully-transparent (opacity ~0) node is not perceivable by ANYONE right now - e.g. this
    // codebase's hover/focus-reveal affordances (PagePreview.tsx's SlotMenuCue/SlotFlipButton:
    // `opacity:0` at rest, `opacity:1` on `:hover`/`:focus-within`/`(pointer:coarse)`) are
    // legitimately invisible until revealed, not a contrast bug - skip rather than false-positive
    // on "text colour equals background" for content nobody can see in this state.
    if (opacity < 0.05) continue;
    const blendedFg = blend({ ...fgColor, a: fgColor.a * opacity }, bg);
    const ratio = contrastRatio(blendedFg, bg);

    const large = isLargeText(el);
    const isDisabled =
      (el as HTMLButtonElement).disabled === true ||
      el.getAttribute("aria-disabled") === "true" ||
      opacity < 0.99;
    const required = isDisabled ? disabledFloor : large ? 4.5 : 7;

    if (ratio < required) {
      contrastFailures.push({
        selector: shortSelector(el),
        text: (el.textContent || "").trim().slice(0, 60),
        fg: toHex(blendedFg),
        bg: toHex(bg),
        ratio: Math.round(ratio * 100) / 100,
        required,
        isLarge: large,
        isDisabled,
        reason: "contrast",
      });
    }

    // off-palette-grey background check, own element only (dedup by resolved hex per page)
    const ownBg = parseColor(cs.backgroundColor);
    if (ownBg && ownBg.a > 0) {
      const hex = toHex(blend(ownBg, { r: 255, g: 255, b: 255 }));
      const key = `${shortSelector(el)}|${hex}`;
      if (isGreyish(ownBg) && !paletteSet.has(hex) && !seenBgKeys.has(key)) {
        seenBgKeys.add(key);
        paletteFailures.push({
          selector: shortSelector(el),
          text: (el.textContent || "").trim().slice(0, 60),
          fg: toHex(blendedFg),
          bg: hex,
          ratio: Math.round(ratio * 100) / 100,
          required,
          isLarge: large,
          isDisabled,
          reason: "off-palette-grey",
        });
      }
    }
  }

  return { contrastFailures, paletteFailures };
}

export interface AuditResult {
  contrastFailures: ContrastFailure[];
  paletteFailures: ContrastFailure[];
}

/**
 * Runs the audit against whatever is currently rendered in `page` (call after any interaction -
 * e.g. expanding an accordion or opening an offcanvas - you want captured). `disabledFloor` is
 * the owner's "aim >=3:1 for disabled text, never below" bar (default 3.0).
 */
export async function auditContrast(
  page: Page,
  disabledFloor = 3.0
): Promise<AuditResult> {
  const result = await page.evaluate(collectInPage, {
    palette: TOKYO11_PALETTE_HEX,
    disabledFloor,
  });
  return result as AuditResult;
}

// Site-wide contrast audit (2026-07-25) OPEN ITEMS - see docs/features/theming.md's
// "2026-07-25 contrast/residual-grey audit" section for the full writeup of each. These are
// real, MEASURED, owner-attention-needed gaps this audit found, deliberately left unfixed
// because resolving them means either accepting an already-ratified token's own known shortfall
// stays visible (items 1/4) or changing a deliberate pre-existing sitewide convention that needs
// an explicit owner call on the replacement (item 2), or reaches into a third-party library's
// own CSS with no token seam at all (item 3) - none of that is this pass's four reported
// defects. Matched structurally (fg/selector patterns), not by page/route, so the SAME
// already-known gap recurring on a different page never counts as a new failure - but anything
// that does NOT match one of these signatures is a genuine, unexpected regression and fails the
// gate.
function isKnownOpenItem(f: ContrastFailure): boolean {
  // 1. $theme-muted (#a3aad0) itself falls short of strict-AAA-normal on raised/panel-family
  // backgrounds (6.39/6.68/5.34:1 measured) - a PR #432-ratified compromise, not new.
  if (f.fg === "#a3aad0" && f.reason === "contrast") return true;
  // 2. $link-color (unset, defaults to $primary/#ff9e64) measures 5.98:1 on panel - a
  // pre-existing, never-previously-measured convention (Navbar.tsx/Footer.tsx/AuthWidget.tsx use
  // the same var(--bs-primary) link styling). Matched on the resolved orange foreground alone,
  // not the tag - inline markup inside a link (e.g. contributions.tsx's `<a><b>ISO-639-1</b></a>`
  // wikipedia reference) puts the direct text node on the `<b>`, not the `<a>`, but it's
  // inheriting the exact same $link-color value either way.
  if (f.fg === "#ff9e64" && f.reason === "contrast") return true;
  // 3. Third-party libraries' own unthemed defaults (react-select's white "Choose..."
  // placeholder, react-dropdown-tree-select's grey tag pills/close button) - no Bootstrap/token
  // seam reaches either; needs its own scoped override stylesheet, out of scope for this pass.
  if (
    (f.selector.includes("rdts") ||
      f.selector.startsWith("span.placeholder")) &&
    f.reason === "contrast"
  ) {
    return true;
  }
  // 4. $theme-danger (#f7768e) as plain text colour measures 6.46:1 - the SAME already-ratified
  // AAA-large-only exception documented for danger-as-button-ink, just recurring as text colour.
  if (f.fg === "#f7768e" && f.reason === "contrast") return true;
  return false;
}

/** Splits a failure list into [newFailures, knownOpenItems] per `isKnownOpenItem` above. Tests
 * should assert `newFailures` is empty (the real regression gate) and log `knownOpenItems` for
 * visibility rather than silently dropping them. */
export function splitKnownOpenItems(failures: ContrastFailure[]): {
  newFailures: ContrastFailure[];
  knownOpenItems: ContrastFailure[];
} {
  const newFailures: ContrastFailure[] = [];
  const knownOpenItems: ContrastFailure[] = [];
  for (const f of failures) {
    (isKnownOpenItem(f) ? knownOpenItems : newFailures).push(f);
  }
  return { newFailures, knownOpenItems };
}

export function formatFailureTable(failures: ContrastFailure[]): string {
  if (failures.length === 0) return "(none)";
  const header =
    "selector | text | fg | bg | ratio | required | large | disabled | reason";
  const rows = failures.map(
    (f) =>
      `${f.selector} | "${f.text}" | ${f.fg} | ${f.bg} | ${f.ratio}:1 | ${f.required}:1 | ${f.isLarge} | ${f.isDisabled} | ${f.reason}`
  );
  return [header, ...rows].join("\n");
}
