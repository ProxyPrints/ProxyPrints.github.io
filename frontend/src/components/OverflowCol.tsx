import styled from "@emotion/styled";
import Col from "react-bootstrap/Col";

interface OverflowColProps {
  heightDelta?: number;
  scrollable?: boolean;
}

// Col isn't a native DOM tag, so Emotion forwards every prop to it by default (including
// these two component-only ones) - Col then spreads its own unrecognised props onto the
// underlying <div>, producing a "React does not recognize the heightDelta prop" console
// warning on every page that renders one. shouldForwardProp keeps the public heightDelta/
// scrollable prop names as-is (no call-site changes needed at any of this component's many
// usages) while stopping them at this boundary.
export const OverflowCol = styled(Col, {
  shouldForwardProp: (prop) => prop !== "heightDelta" && prop !== "scrollable",
})<OverflowColProps>`
  position: relative;
  // define height twice - first as a fallback for older browser compatibility,
  // then using dvh to account for the ios address bar
  height: calc(100vh - ${(props) => props.heightDelta ?? 0}px);
  height: calc(100dvh - ${(props) => props.heightDelta ?? 0}px);
  overflow-y: ${(props) => (props.scrollable === false ? "hidden" : "scroll")};
  overscroll-behavior: none;
  scrollbar-width: thin;
`;
