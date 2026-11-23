# Updater signing key

OLGA Companion updates itself from the `latest.json` of the newest GitHub Release. Before it
installs anything, the app checks the installer's minisign signature against the public key built
into it (`plugins.updater.pubkey` in `src-tauri/tauri.conf.json`). An installer signed by any other
key is refused, even if it is served from the real release page.

## Current keys

| Key id | Used by | Status |
| --- | --- | --- |
| `1CC29D6373D6F811` | 0.1.1 – 0.1.23 trust it | Signed 0.1.1 – 0.1.24, then retired |
| `883C100533D4B36A` | 0.1.24 trusts it | Retired without signing a release |
| `8CBC15C2BC59B946` | 0.1.25 and later trust it | Signs 0.1.25 onward |

The private keys stay on the maintainer's machine, outside this repository, and are never
uploaded. Only the public half appears here.

## Why 0.1.24 is signed with the old key

An installed app can only verify an update with the key it already has. So the hand-over takes one
release:

1. 0.1.24 is signed with the **old** key, which every installed 0.1.23 or earlier trusts, and it
   carries the **new** public key.
2. The plan was to sign 0.1.25 onward with that new key. The next section explains why 0.1.25
   used a third key instead, so the hand-over in 0.1.24 did not carry users forward.

## 0.1.25: a second rotation without a hand-over

The key that 0.1.24 trusts (`883C100533D4B36A`) was retired before it signed a release: its
password could not be supplied when 0.1.25 was built. 0.1.25 is therefore signed with a new key (`8CBC15C2BC59B946`) and carries its
public half. No app older than 0.1.25 can verify it.

**What to do:** if your app is older than 0.1.25, download the latest release's installer from the
release page and run it once. Your cases and settings stay. From 0.1.25 on, the app updates itself
(0.1.25 → 0.1.26 was checked against the key built into the shipped 0.1.25).

## If a key is ever lost or exposed

Stop publishing, generate a new key pair, and repeat the hand-over above. If the old key was
exposed, anyone holding it could sign an update that apps trusting it would accept. Releases that
announce a rotation say so in their notes, and the release page lists the key id in use.
