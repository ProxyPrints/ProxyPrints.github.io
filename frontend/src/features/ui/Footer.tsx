import Link from "next/link";

import { useGetBackendInfoQuery } from "@/store/api";

function Spacer() {
  return (
    <span style={{ marginLeft: 0.25 + "em", marginRight: 0.25 + "em" }}> </span>
  );
}

export default function Footer() {
  const backendInfoQuery = useGetBackendInfoQuery();
  return (
    <>
      <hr />
      <footer className="page-footer font-small blue">
        <div className="footer-copyright text-center py-3">
          ProxyPrints, forked from chilli_axe&apos;s mpc-autofill, made with ♥️
          <Spacer />•<Spacer />
          <a
            href="https://github.com/ProxyPrints/ProxyPrints.github.io"
            target="_blank"
          >
            GitHub
          </a>
          {backendInfoQuery.isSuccess && backendInfoQuery.data?.reddit != null && (
            <>
              <Spacer />•<Spacer />
              <a href={backendInfoQuery.data.reddit} target="_blank">
                Reddit
              </a>
            </>
          )}
          {backendInfoQuery.isSuccess &&
            backendInfoQuery.data?.discord != null && (
              <>
                <Spacer />•<Spacer />
                <a href={backendInfoQuery.data.discord} target="_blank">
                  Discord
                </a>
              </>
            )}
          <Spacer />•<Spacer />
          <Link href="/about">About</Link>
          <Spacer />•<Spacer />
          <Link href="/about#privacy-policy">Privacy Policy</Link>
        </div>
        <div
          className="footer-copyright text-center pb-3"
          data-testid="footer-source-disclosure"
        >
          <small className="text-muted">
            Card data comes from Scryfall. Card images are hosted by their
            original uploaders &mdash; ProxyPrints indexes them, it doesn&apos;t
            store them.
          </small>
        </div>
      </footer>
    </>
  );
}
