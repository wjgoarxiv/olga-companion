# Contributing to OLGA Companion

Thanks for helping. This page covers the development setup, the tests, and how a change gets merged.

## Before you start

- For a bug, open an issue with the bug template. Say which version you run (Settings shows it), which OLGA version you have, and the steps that reproduce it.
- For a feature, open an issue with the feature template first, so we can agree on the shape before you write code.
- For a security problem, do not open an issue. Follow [SECURITY.md](./SECURITY.md).
- Never attach a customer case, a licensed OLGA or Multiflash file, or an API key. Make a small neutral case that shows the problem instead.

## Development setup

You need:

- Windows 10 or 11 (x64). OLGA itself only runs on Windows. Much of the code also runs and tests on Linux or WSL.
- Node.js 22.12 or newer
- Python 3.11 and [uv](https://docs.astral.sh/uv/)
- Rust and the Tauri 2 prerequisites, only if you build the desktop shell
- A licensed local OLGA installation, only for end-to-end runs. The unit tests do not need OLGA.

```sh
git clone https://github.com/wjgoarxiv/olga-companion.git
cd olga-companion
npm ci
uv sync --extra results --group dev
```

Run the app in development:

```sh
npm run dev:sidecar   # the Python sidecar on 127.0.0.1:8865
npm run dev           # the web UI on 127.0.0.1:5273
npm run dev:app       # or both inside the Tauri shell
```

## Tests

Run these before you open a pull request:

```sh
npm run test:frontend   # frontend unit tests
npm run typecheck       # TypeScript
npm run test:backend    # Python tests (pytest)
npm run verify          # all of the above plus a production build
```

Rules for tests:

- A behaviour change comes with a regression test that fails before the change and passes after it.
- Do not weaken, skip or delete an existing test to make a change pass. If a test is wrong, explain why in the pull request.
- The safety tests (approval cards, file writes, run gates) are a floor, not a target. Their count must not go down.

## Design rules for UI changes

- Square corners (radius 0), stepped motion, and colours from the theme tokens only.
- Every new string exists in English and Korean.
- Every control works with the keyboard and has a name a screen reader can read.
- Check light and dark themes.

## Commits and pull requests

1. Branch from `master` and keep the change small and focused.
2. Write commit messages in the imperative with a type prefix, for example `fix: the run strip shows why a run stopped`. Common prefixes: `feat`, `fix`, `docs`, `test`, `chore`, `release`.
3. Stage files by name. Do not commit build output, local logs, secrets or editor folders.
4. Open a pull request with the template. Say what you changed, why, and what you verified (tests and, for UI, a screenshot).
5. A maintainer reviews it. Anything that writes files, saves cases or starts OLGA runs gets extra scrutiny: it must still stop at an approval card.

## Licence

By contributing you agree that your contribution is licensed under the [Apache License 2.0](./LICENSE), the licence of this project.

## Code of conduct

Everyone taking part follows the [Code of Conduct](./CODE_OF_CONDUCT.md).
