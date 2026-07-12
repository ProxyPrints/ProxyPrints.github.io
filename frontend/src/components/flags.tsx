import styled from "@emotion/styled";
import React from "react";

// Flag artwork vendored from lipis/flag-icons (MIT license):
// https://github.com/lipis/flag-icons — see that repo's LICENSE for the
// required copyright notice.
const FlagImg = styled.img`
  width: 1.4em;
  height: 1em;
  vertical-align: -0.15em;
`;

export const CanadaFlag = () => (
  <FlagImg src="/flag-canada.svg" alt="Canada flag" />
);

export const ChinaFlag = () => (
  <FlagImg src="/flag-china.svg" alt="China flag" />
);

export const USAFlag = () => <FlagImg src="/flag-usa.svg" alt="USA flag" />;
