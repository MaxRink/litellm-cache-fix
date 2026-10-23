# LiteLLM dashboard UI dependency security update

Date: 2026-10-24

Scope: `ui/litellm-dashboard` only. The runtime Dockerfile and production
gateway were not changed.

## Advisory and path review

- Next.js `16.3.8` was updated to `16.4.1`, the patched floor for the official
  `GHSA-673q-mjm6-r5xr` advisory (affected through 16.4.0). The dashboard is a
  static-export App Router application; source review found no `use cache`,
  `cacheComponents`, `ImageResponse`, or `next/image` usage. The dependency is
  still updated because the advisory recommends upgrading even where the
  vulnerable feature is not enabled.
- Vite `7.3.5` was updated to `7.3.7`, the official patched version for
  `GHSA-9jrq-w75r-8gcw` and `GHSA-rq7h-c2jc-7f22` (affected through 7.3.6).
  Vite is used by the Vitest test runner; no custom middleware, `middlewareMode`,
  or network-exposed Vite dev server was found in the dashboard.
- Vitest `4.1.11`, `@vitest/coverage-v8`, and `@vitest/ui` were updated together
  to `4.1.12` for the official `GHSA-qxg6-89mg-rqv8` and
  `GHSA-xp26-3454-mjgp` advisories. These are test-only dependencies and the
  update was kept aligned to avoid peer-dependency drift.

The only direct package manifest containing these versions is
`ui/litellm-dashboard/package.json`; its lockfile is the only lockfile changed.

## Validation

- `npm ci --ignore-scripts`: passed; 717 packages installed.
- `npm audit --json`: 0 vulnerabilities after the update.
- `npm run typecheck`: passed.
- `npx next build --webpack`: passed; 56 static routes generated.
- `npm run test:unit -- --reporter=dot`: 4,080 passed, 2 expected failures, 4
  failures. The failures are existing environment-sensitive tests: three
  jsdom localStorage tests under Node 26 without a `--localstorage-file`, and
  one ESLint fetch-rule test exceeding the 60-second timeout. No dependency
  update failure was observed. Turbopack was separately attempted but hit an
  environment-specific worker bind restriction; the Webpack build is the
  successful production-build proof.

A clean base-control worktree at commit `5cb5148` with the original lockfile
produced the identical 4,080/2-expected/4-failure result and the same four
failure locations. This confirms the failures predate this dependency update;
they are not a regression from Next, Vite, or Vitest changes.

No live UI/gateway call, secret, request body, or production deployment was
used.
