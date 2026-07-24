/**
 * Nav+footer redesign (2026-07-22, N8) - the three-tier footer that now carries what the
 * slimmed-down navbar dropped: Contributions as an ordinary link (its PROMINENCE lives on the
 * Wiki page's own content instead, see docs/user-guide.md), the standing chilli_axe credit
 * (linked to their GitHub only - the owner explicitly declined a Buy-Me-a-Coffee button here;
 * the unrelated SupportDeveloperModal/Coffee.tsx affordance elsewhere in the app is untouched),
 * Privacy/Terms/About, GitHub/Reddit/Discord, and the existing Scryfall source-disclosure line.
 * Footer's own "Sources" link opens the same BackendConfig offcanvas the navbar's Sources
 * button does, via a small local (per-mount) show/hide state - Footer has no dedicated route
 * to link "Sources" to, and a plain dead link would be worse than the trivial duplicated state.
 */
import styled from "@emotion/styled";
import Link from "next/link";
import React, { useState } from "react";

import { BackendConfig } from "@/features/backend/BackendConfig";
import { useGetBackendInfoQuery } from "@/store/api";

const FooterRoot = styled.footer`
  background-color: var(--theme-raised-bg);
  border-top: 1px solid #17222e;
  padding: 1.75rem 1.5rem 1.5rem;
  margin-top: 1.25rem;
`;

const Tier1 = styled.div`
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 1.5rem 3.75rem;
  padding-bottom: 1.25rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
`;

const FooterColumn = styled.div`
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  min-width: 130px;
`;

const ColumnHeading = styled.h4`
  margin: 0 0 0.1rem;
  font-size: 0.72rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.4);
  font-weight: 700;
`;

const footerLinkStyles = `
  color: rgba(255, 255, 255, 0.75);
  text-decoration: none;
  font-size: 0.95rem;
  font-weight: 600;
  &:hover {
    color: var(--bs-primary);
  }
`;

const FooterLink = styled(Link)`
  ${footerLinkStyles}
`;

const FooterExternalLink = styled.a`
  ${footerLinkStyles}
`;

const FooterLinkButton = styled.button`
  ${footerLinkStyles}
  background: none;
  border: 0;
  padding: 0;
  text-align: left;
  cursor: pointer;
`;

const Tier2 = styled.div`
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 0.35rem;
  padding: 1.25rem 0 0.5rem;
  text-align: center;
`;

const CreditText = styled.span`
  color: var(--bs-body-color);
  font-size: 0.95rem;
`;

const CreditLink = styled.a`
  color: var(--bs-primary);
  font-weight: 700;
  text-decoration: none;
  &:hover {
    text-decoration: underline;
  }
`;

const Tier3 = styled.div`
  text-align: center;
  padding-top: 0.75rem;
`;

export default function Footer() {
  const backendInfoQuery = useGetBackendInfoQuery();
  const [showBackendConfig, setShowBackendConfig] = useState(false);

  return (
    <>
      <FooterRoot data-testid="site-footer">
        <Tier1>
          <FooterColumn>
            <ColumnHeading>ProxyPrints</ColumnHeading>
            <FooterLink href="/contributions">Contributions</FooterLink>
            <FooterLink href="/guide">Wiki</FooterLink>
            <FooterLinkButton
              type="button"
              onClick={() => setShowBackendConfig(true)}
              data-testid="footer-sources-button"
            >
              Sources
            </FooterLinkButton>
          </FooterColumn>
          <FooterColumn>
            <ColumnHeading>Legal</ColumnHeading>
            <FooterLink href="/about">About</FooterLink>
            <FooterLink href="/about#privacy-policy">Privacy Policy</FooterLink>
            <FooterLink href="/about#terms-of-use">Terms</FooterLink>
          </FooterColumn>
          <FooterColumn>
            <ColumnHeading>Project</ColumnHeading>
            <FooterExternalLink
              href="https://github.com/ProxyPrints/ProxyPrints.github.io"
              target="_blank"
            >
              GitHub
            </FooterExternalLink>
            {backendInfoQuery.isSuccess &&
              backendInfoQuery.data?.reddit != null && (
                <FooterExternalLink
                  href={backendInfoQuery.data.reddit}
                  target="_blank"
                >
                  Reddit
                </FooterExternalLink>
              )}
            {backendInfoQuery.isSuccess &&
              backendInfoQuery.data?.discord != null && (
                <FooterExternalLink
                  href={backendInfoQuery.data.discord}
                  target="_blank"
                >
                  Discord
                </FooterExternalLink>
              )}
          </FooterColumn>
        </Tier1>
        <Tier2>
          <CreditText>
            ProxyPrints &mdash; forked from{" "}
            <CreditLink
              href="https://github.com/chilli-axe"
              target="_blank"
              data-testid="footer-chilli-axe-credit"
            >
              chilli_axe
            </CreditLink>
            &apos;s mpc-autofill, made with ♥️
          </CreditText>
        </Tier2>
        <Tier3 data-testid="footer-source-disclosure">
          <small className="text-muted">
            Card data comes from Scryfall. Card images are hosted by their
            original uploaders &mdash; ProxyPrints indexes them, it doesn&apos;t
            store them.
          </small>
        </Tier3>
      </FooterRoot>
      <BackendConfig
        show={showBackendConfig}
        handleClose={() => setShowBackendConfig(false)}
      />
    </>
  );
}
