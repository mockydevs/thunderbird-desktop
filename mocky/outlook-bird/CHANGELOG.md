# Changes

## 0.3.2

- Reduce folder-row height and account-group spacing while preserving text size,
  unread counts, icons and keyboard focus.

## 0.3.1

- Keep PR numbers and author names unbroken in PR/Author/What tables.
- Give descriptions the remaining width and natural multiline row heights.
- Preserve other email tables and restore the original classes on disable.
- Add real-reader regression coverage for long identifiers, long authors,
  multiline descriptions and reading-pane containment.

## 0.3.0

- Shared message formatting across single readers and conversations.
- Accessible stalled-load errors/retry and empty-body explanations.
- Correct focus when opening a second conversation message by keyboard.
- Coalesced conversation updates, indexed message lookup and navigation cleanup.
- Native compose styling and local draft/reply/forward regression coverage.
- Responsive image/code wrapping and high-contrast keyboard focus.
- Profile-specific installation, original-state restore and version rollback.
- Atomic XPI writes, deterministic builds, checksum installer archives and CI.
- Preserve remote-image policy unless explicitly changed; restrict compatibility
  to the tested Thunderbird 159 major version.

## 0.2.1

Private sender-photo configuration and restart regression checks.
