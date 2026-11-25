# Security policy

Undo stores copies of your files and can write files back on restore, so security problems
matter. Thank you for reporting them responsibly.

**Quick links:** [Contributing](CONTRIBUTING.md) · [Architecture › Communication](docs/ARCHITECTURE.md#communication) ·
[Local API](docs/API.md) · [Recovery › Ransomware](docs/RECOVERY.md#ransomware) ·
[Documentation index](docs/README.md)

## Supported versions

| Version | Security fixes |
|---|---|
| 1.2.x (latest) | Yes |
| 1.1.x and older | No: update to the [latest release](https://github.com/Madhur-Prakash/Undo/releases/latest) |

## Reporting a vulnerability

**Please do not open a public issue, discussion or pull request for a security problem.**

Report it privately through GitHub:

1. Open the repository's **[Security tab](https://github.com/Madhur-Prakash/Undo/security)**.
2. Click **Report a vulnerability**.
3. Describe:
   * what an attacker can do, and what they need first (local account, network access, a
     malicious file in a tracked folder, …),
   * steps to reproduce,
   * the Undo version (`undo --version`) and your OS,
   * if you have one, a suggested fix.

**What happens next:**

* You get a reply within **7 days** saying whether the report is confirmed.
* For confirmed problems, a fix is prepared privately and released as soon as practical. Serious
  issues are prioritised.
* You are credited in the release notes and the advisory, unless you prefer not to be.
* Please keep the details private until a fixed version is released.

## What counts as a vulnerability

**In scope**, for example:

* Another local user, a website, or a remote machine reading or changing your history, or
  restoring files, through the local API (token or loopback bypass).
* A restore writing outside the destination you chose (path traversal), or overwriting a file
  without the overwrite confirmation.
* Corrupt or crafted stored data being written to your files without failing verification.
* The installer, the update scripts or autostart running something other than Undo, or
  weakening file permissions.
* The API token or the data directory being readable by other users where Undo set the
  permissions.

**Out of scope:**

* **Malware running as your own user account.** It can read and delete your files and Undo's
  data directory just like you can. Undo is not a backup and not an anti-ransomware tool; see
  [Recovery › Ransomware](docs/RECOVERY.md#ransomware).
* Turning on `api.allow_remote` and exposing the API to a network. That is unsupported, and the
  setting warns about it.
* Disk failure, theft, or loss of the data directory.
* Denial of service by filling the disk with huge files in a tracked folder (use exclusions,
  the maximum file size and the storage quota).

## How Undo is protected

* **Local API only:** the daemon listens on `127.0.0.1`. A non-loopback address needs
  `api.allow_remote`.
* **Token:** every API route except `/ping` needs a random token (32 bytes from Python's
  `secrets`), compared in constant time. It is stored in the data directory with owner-only
  permissions (`chmod 600` on Linux, an `icacls` rule for your account on Windows).
* **No silent overwrites:** restores need explicit overwrite permission, and the current content
  is versioned first.
* **Verified data:** every stored object is verified by its BLAKE3 hash when it is written and
  again before every restore.
* **Tracked files only:** comparing a version with a file on disk, and merging, only read and
  write files inside tracked folders, so the API cannot be used to read arbitrary files.
* **Per-user install:** the Windows installer and autostart need no administrator rights, and
  the daemon runs as you.

Details: [Architecture › Communication](docs/ARCHITECTURE.md#communication) and
[Local API](docs/API.md).

---

Related: [Contributing](CONTRIBUTING.md) · [Troubleshooting](docs/TROUBLESHOOTING.md) · [Documentation index](docs/README.md)
