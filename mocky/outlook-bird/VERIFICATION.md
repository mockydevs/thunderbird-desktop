# Verification — 2026-10-29

Tested with the installed Thunderbird 159.0 on Linux. The customization uses the
native message browser and attachment handlers; a full source-built application
has not been produced.

Passed checks:

- Clean-profile installation and correctly styled horizontal toolbar.
- Four-message conversation with global search indexing disabled.
- Full message content, 14px reading text and consistent body insets.
- Content-sized cards with no nested text scrollbar or unused bottom region.
- Attachment cards above the body, file-menu targeting and dropdown spacing.
- Keyboard expansion with retained focus and two simultaneously expanded cards.
- Opaque sticky subject header and stable space for the outer scrollbar.
- All/Unread filtering and separate, small message-list action icons.
- Image loading from a loopback HTTP server without a permission prompt.
- Promotional notifications and the start page disabled.
- Repeated extension reloads without missing initials, duplicate controls or
  destroyed-document exceptions.
- Install/restore preserves unrelated preferences and a pre-existing stylesheet.
- JavaScript syntax, Python compilation and JSON/package validation.

The initials regression check was also run against a separate deliberately
broken package with empty initials. It failed at the expected assertion. The
unchanged, passing package is the one committed here.

The UI runner uses a temporary local-only profile and sample addresses under
`example.test`. Sending mail, opening attachments, and saving to the filesystem
through Thunderbird's attachment UI were not exercised. Actual send/receive
behaviour across providers is not certified by these local checks.

Upstream `mach commlint`, mochitests and the full Thunderbird/Firefox build were
not run: this standalone package was checked with the installed application,
without a parent Firefox build checkout.
