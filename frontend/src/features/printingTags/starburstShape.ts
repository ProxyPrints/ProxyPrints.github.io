/**
 * Procedurally generates the jagged "explosion" starburst silhouette used behind the
 * Vote queue (see printingQueue.tsx) - alternating spike-tip/valley vertices around
 * a circle, with the tip radius heavily randomized per spike so the outline reads as an
 * irregular burst rather than a uniform star (matching the reference clip-art starburst
 * this was modeled on, e.g. https://i.sstatic.net/xpRS9.gif). Computed once at module load
 * with a fixed seed rather than Math.random() at render time, so the server-rendered HTML
 * (Next.js static export) and the client's first render produce byte-identical markup -
 * using real randomness here would cause a hydration mismatch.
 */

function mulberry32(seed: number): () => number {
  let a = seed;
  return function random() {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

interface StarburstLayerOptions {
  seed: number;
  spikes: number;
  tipRadiusRange: [number, number];
  valleyRadiusRange: [number, number];
}

const VIEWBOX_SIZE = 1100;
const CENTER = VIEWBOX_SIZE / 2;

function generateStarburstPoints({
  seed,
  spikes,
  tipRadiusRange,
  valleyRadiusRange,
}: StarburstLayerOptions): string {
  const random = mulberry32(seed);
  const vertexCount = spikes * 2;
  const points: Array<string> = [];
  for (let i = 0; i < vertexCount; i++) {
    const angle = (i / vertexCount) * Math.PI * 2;
    const [min, max] = i % 2 === 0 ? tipRadiusRange : valleyRadiusRange;
    const radius = min + random() * (max - min);
    const x = CENTER + Math.cos(angle) * radius;
    const y = CENTER + Math.sin(angle) * radius;
    points.push(`${x.toFixed(2)},${y.toFixed(2)}`);
  }
  return points.join(" ");
}

export const STARBURST_VIEWBOX = `0 0 ${VIEWBOX_SIZE} ${VIEWBOX_SIZE}`;

// colours sampled directly from the reference gif's flat fill (no gradients/outlines there)
export const STARBURST_BACKGROUND_COLOR = "#ff4719";
export const STARBURST_OUTER_COLOR = "#4d8ddf";
export const STARBURST_INNER_COLOR = "#ffffff";

// The reference gif isn't a single static shape - it flickers between several jagged
// point-sets (a classic hand-drawn "explosion" vibration), so each layer precomputes a
// handful of frames up front (still fully deterministic/seeded) rather than one fixed
// shape. See useStarburstFrame in printingQueue.tsx for the interval that cycles through
// these client-side, after the (hydration-safe) first paint always shows frame 0.
const FRAME_COUNT = 5;

function generateStarburstFrames(
  baseSeed: number,
  layer: Omit<StarburstLayerOptions, "seed">
): Array<string> {
  return Array.from({ length: FRAME_COUNT }, (_, i) =>
    generateStarburstPoints({ ...layer, seed: baseSeed + i * 97 })
  );
}

// Valley radii sit much closer to their tip radii than a "pure star" would use - the
// reference gif's core is a full, round belly with jagged spikes only at the fringe, not a
// thin spindly shape throughout (measured directly off the reference frame: the blue
// layer's radial boundary averages ~70% of its own max, not ~30%).
export const STARBURST_OUTER_FRAMES = generateStarburstFrames(1337, {
  spikes: 48,
  tipRadiusRange: [370, 540],
  valleyRadiusRange: [220, 310],
});

export const STARBURST_INNER_FRAMES = generateStarburstFrames(4242, {
  spikes: 40,
  tipRadiusRange: [230, 400],
  valleyRadiusRange: [130, 200],
});
