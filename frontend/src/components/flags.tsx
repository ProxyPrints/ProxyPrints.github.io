import styled from "@emotion/styled";
import React from "react";

const FlagSvg = styled.svg`
  width: 1.4em;
  height: 1em;
  vertical-align: -0.15em;
`;

// Simplified 3-lobe maple leaf silhouette (apex at top, two side lobes,
// short stem at the base) — legible at ~1em rather than a precise botanical
// outline.
const MapleLeafPath =
  "M12 2.2 L12.9 5 L15.4 3.6 L14.6 6.1 L17 5.6 L14.9 7.6 L16.6 8.6 " +
  "L14.3 9 L15 11 L12.9 10.2 L13.1 12 L12 10.8 L10.9 12 L11.1 10.2 " +
  "L9 11 L9.7 9 L7.4 8.6 L9.1 7.6 L7 5.6 L9.4 6.1 L8.6 3.6 L11.1 5 Z " +
  "M11.4 12 L12.6 12 L12.4 13.6 L11.6 13.6 Z";

export const CanadaFlag = () => (
  <FlagSvg viewBox="0 0 24 16" role="img" aria-label="Canada flag">
    <rect width="24" height="16" fill="#FFFFFF" />
    <rect width="6" height="16" fill="#FF0000" />
    <rect x="18" width="6" height="16" fill="#FF0000" />
    <path d={MapleLeafPath} fill="#FF0000" />
  </FlagSvg>
);

const smallStar = (cx: number, cy: number, r: number) => {
  const points = Array.from({ length: 10 }, (_, i) => {
    const angle = (Math.PI / 5) * i - Math.PI / 2;
    const radius = i % 2 === 0 ? r : r * 0.4;
    return `${(cx + radius * Math.cos(angle)).toFixed(2)},${(
      cy +
      radius * Math.sin(angle)
    ).toFixed(2)}`;
  });
  return points.join(" ");
};

export const ChinaFlag = () => (
  <FlagSvg viewBox="0 0 24 16" role="img" aria-label="China flag">
    <rect width="24" height="16" fill="#DE2910" />
    <polygon points={smallStar(5, 5, 2.6)} fill="#FFDE00" />
    <polygon points={smallStar(9.5, 2.2, 0.9)} fill="#FFDE00" />
    <polygon points={smallStar(11, 4.7, 0.9)} fill="#FFDE00" />
    <polygon points={smallStar(11, 7.5, 0.9)} fill="#FFDE00" />
    <polygon points={smallStar(9.2, 9.7, 0.9)} fill="#FFDE00" />
  </FlagSvg>
);

export const USAFlag = () => (
  <FlagSvg viewBox="0 0 24 16" role="img" aria-label="USA flag">
    <rect width="24" height="16" fill="#FFFFFF" />
    {Array.from({ length: 7 }, (_, i) => (
      <rect
        key={i}
        y={(i * 2 * 16) / 13}
        width="24"
        height={16 / 13}
        fill="#B22234"
      />
    ))}
    <rect width="10" height={(16 * 7) / 13} fill="#3C3B6E" />
    {Array.from({ length: 5 }, (_, row) =>
      Array.from({ length: row % 2 === 0 ? 3 : 2 }, (_, col) => (
        <circle
          key={`${row}-${col}`}
          cx={1.7 + col * 2.8 + (row % 2 === 0 ? 0 : 1.4)}
          cy={0.9 + row * 1.6}
          r="0.4"
          fill="#FFFFFF"
        />
      ))
    )}
  </FlagSvg>
);
