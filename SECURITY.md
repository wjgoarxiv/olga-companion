# Security Policy

## Supported versions

Only the latest release gets security fixes. The app checks for updates and installs signed updates when you approve them.

| Version | Supported |
|---|---|
| Latest release ([releases](https://github.com/wjgoarxiv/olga-companion/releases/latest)) | Yes |
| Older releases | No, please update |

## Reporting a vulnerability

Please report security problems privately. Do not open a public issue.

1. Use GitHub's private reporting: the **Security** tab of this repository, then **Report a vulnerability**.
2. If that is not available to you, contact the maintainer through the details on the [maintainer's GitHub profile](https://github.com/wjgoarxiv) and ask for a private channel.

Please include the app version, your Windows version, the steps to reproduce, and what an attacker could gain. Do not include real API keys, customer cases or licensed vendor files.

You can expect a first reply within 7 days. We will tell you when a fix is planned and credit you in the release notes if you want.

## In scope

- **API keys**: how the app stores, sends or could leak the keys for AI providers you connect in Settings.
- **Update signing**: anything that would let an unsigned or tampered update install, or bypass the updater signature check.
- **Local file access**: any way the assistant, a case file or a crafted input could read or write files outside the folder you chose, or change a file without an approval card.
- **Run and approval gates**: any way to start an OLGA run, save a case or write a file without the user's click.
- **The local sidecar**: the HTTP service on `127.0.0.1` that the app talks to, for example requests from a web page or another local user.

## Out of scope

- Problems in OLGA, Multiflash or other licensed SLB software. Report those to SLB.
- Problems in the AI providers themselves.
- Attacks that need an already compromised Windows account with full rights.
