# Verification

Version 0.3.0 was exercised on Linux with the official Thunderbird 159.0 binary.
The package is an extension and profile theme, not a rebuilt Thunderbird binary.

## Automated checks

- 13 Python installer/build tests: reproducible XPI builds, translation/schema
  agreement, privacy-policy preservation, repeated updates, independent profile
  backups, original-state restore, XPI/style rollback, partial-copy failure
  recovery, failed-build protection, checksum coverage, running-process guard
  and unsupported-version rejection.
- Real Thunderbird UI checks in a temporary Local Folders profile: toolbar,
  read filters, opaque conversation header, shared scrollbar, body spacing and
  14px reading text, top attachment cards and native attachment menus.
- HTML and plain-text single readers, navigation without duplicate attachment
  controls, and separate message windows.
- Stalled body load, accessible error/retry, native message reload and genuinely
  empty MIME bodies (excluding Thunderbird's generated header tables).
- A 120-message thread with only one initial message browser and independent
  keyboard expansion; narrow-window fit and reading-pane containment at 150%
  zoom. This is a bounded fixture check, not a general performance benchmark.
- Native HTML composition, visible attachment, native signature, save/reopen
  of a local draft with its attachment, quoted reply, forward as attachment and
  draft persistence after application restart. No outgoing server is configured.
- Sender-photo decoding, repeated extension reload, cold application restart,
  disable/enable cleanup and absence of dead-document teardown errors.
- Forced-colour focus declarations were activated directly through CSSOM and
  checked for one visible border. Headless Linux did not expose an active OS
  forced-colour theme, so this does not certify an actual OS high-contrast session.

The timeout test was run against a separate deliberately broken package whose
load timeout marked the browser ready instead of showing an error. It failed
at the stalled-message regression assertion. The unchanged source was then run
successfully again. No user profile was used in these tests.

## Limits

Live provider authentication, send/receive, encrypted messages, actual attachment
opening/saving, assistive-technology output, Windows/macOS and other Thunderbird
major versions were not certified. No live messages, tracking events or test
emails were sent. The loopback image check uses a local HTTP server only.

Upstream `mach commlint`, mochitests, leak instrumentation and full Thunderbird /
Firefox compilation were not run: this standalone package was tested using the
installed application without a parent Firefox build checkout. GitHub Actions
runs package/installer checks; it does not claim real Thunderbird UI coverage.

## 0.3.1 table layout

The full local UI suite passed with four additional assertions covering full PR
identifiers and author names on one line, multiline descriptions, reading-pane
containment and unchanged unrelated tables. The layout is restricted to simple
three-column PR/Author/What (or Description) tables with no merged cells.
