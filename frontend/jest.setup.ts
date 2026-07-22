// The below can be used in a Jest global setup file or similar for your testing set-up
import "@testing-library/jest-dom";
// Polyfill "window.fetch" used in the React component.
import "whatwg-fetch";

import { webcrypto } from "node:crypto";

import { loadEnvConfig } from "@next/env";
import { configure as configureDom } from "@testing-library/dom";
import { configure as configureReact } from "@testing-library/react";
// TODO: https://github.com/alfg/ping.js/issues/29#issuecomment-487240910
// @ts-ignore
import Ping from "ping.js";

import { server } from "@/mocks/server";

// jsdom's `crypto` only implements getRandomValues, not the full SubtleCrypto API - Node's own
// WebCrypto implementation is spec-compliant (the same API surface real browsers implement),
// so it's a safe like-for-like polyfill for savedDeckCrypto.ts's tests
// (docs/proposals/proposal-g-user-accounts-saved-decks.md §8).
if (typeof globalThis.crypto?.subtle === "undefined") {
  Object.defineProperty(globalThis, "crypto", {
    value: webcrypto,
    configurable: true,
  });
}

configureReact({ asyncUtilTimeout: 10_000 });
configureDom({ asyncUtilTimeout: 10_000 });

// retrieved from https://stackoverflow.com/a/68539103/13021511
global.matchMedia =
  global.matchMedia ||
  function () {
    return {
      matches: false,
      addListener: function () {},
      removeListener: function () {},
    };
  };

// jsdom has no ResizeObserver - needed at MODULE LOAD time (not just render time) by
// @dnd-kit/react's own ResizeNotifier (SourceSettings.tsx -> GridSelectorFilters.tsx ->
// SelectVersionResults.tsx's import graph), so this has to be a real global, set up here
// (setupFilesAfterEnv runs before any test file's own imports are required), not a per-test
// mock - a per-test `jest.fn()` stub assigned inside a test/beforeEach runs too late to satisfy
// an import-time reference. Funnel round (funnel-spec.md), SelectVersionResults.test.tsx.
if (typeof global.ResizeObserver === "undefined") {
  global.ResizeObserver = class {
    observe() {
      return undefined;
    }
    unobserve() {
      return undefined;
    }
    disconnect() {
      return undefined;
    }
  };
}

const defaultExport = async () => {
  const projectDir = process.cwd();
  loadEnvConfig(projectDir);
};

// Establish API mocking before all tests.
beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });

  // we cannot use MSW to mock this ping out because ping.js works by loading favicon.ico as an image
  // therefore, we need to mock the ping implementation such that the server is always "alive"
  // typing these with `any` is pretty lazy but this is just in the test framework so who cares tbh
  jest
    .spyOn(Ping.prototype, "ping")
    .mockImplementation(function (source: any, callback: any) {
      return callback(null); // null indicates no error -> successful ping
    });
});

beforeEach(() => {
  // IntersectionObserver isn't available in test environment
  const mockIntersectionObserver = jest.fn();
  mockIntersectionObserver.mockReturnValue({
    observe: () => null,
    unobserve: () => null,
    disconnect: () => null,
  });
});

// Reset any request handlers that we may add during the tests,
// so they don't affect other tests.
afterEach(() => {
  server.resetHandlers();
  jest.restoreAllMocks();
});

// Clean up after the tests are finished.
afterAll(() => {
  server.close();

  jest.spyOn(Ping.prototype, "ping").mockRestore();
});

export default defaultExport;
