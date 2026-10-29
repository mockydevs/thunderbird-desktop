# Mocky Mail layout

An Outlook-inspired desktop layout for Thunderbird, maintained in this fork.
The current implementation is a local MailExtension plus a profile stylesheet;
it runs on the installed Thunderbird executable. It is not a separately built
Thunderbird distribution.

![Local sample mailbox](preview.png)

## Current behaviour

- Light blue folder pane, narrow message cards and a mail-action toolbar.
- Sender initials, cached message previews and All/Unread controls.
- Multiple messages can stay expanded in one conversation scroll area.
- An opaque sticky subject header and a separate gutter for the scrollbar.
- Comfortable body margins and 14px reading text, with monospace code preserved.
- Attachment cards below the sender, with filename, size and native file menus.
- Native reply, forward, delete, archive, read-status and print commands.
- Promotional notifications and the start page disabled by the setup script.
- Remote images allowed for all senders. This also permits open-tracking images.

Mail content is displayed by Thunderbird's native message browser. Attachment
commands use Thunderbird's existing handlers; files are not opened automatically.
The extension does not define a remote service or upload mailbox data.

## Install

Tested on Linux with Thunderbird 159.0. Back up the profile and close Thunderbird.
Python 3 is required; the package has no third-party Python dependencies.

```sh
cd mocky/outlook-bird
python3 manage.py install
```

The installer locates the default profile, saves its previous appearance and
settings, and installs the stylesheet. Select a different initialized profile
with `--profile /absolute/path/to/profile`.

Start Thunderbird and use **Add-ons and Themes → gear → Install Add-on From
File** to select the generated `outlook-bird.xpi`. The extension uses a privileged
experiment API because a normal theme cannot add desktop mail controls.

Use Thunderbird's built-in light theme. Choose Vertical View and Cards View if
those were changed. Pane widths remain adjustable using the normal dividers.

To rebuild the extension after editing its source:

```sh
python3 manage.py build
```

## Restore

Close Thunderbird, then run:

```sh
python3 manage.py restore
```

This restores the saved appearance settings, removes this extension and preserves
mail files and unrelated preferences. Private backups are stored under
`~/.local/state/outlook-bird/`; they are not part of this repository.

## Verification

```sh
python3 manage.py build
python3 tests/smoke.py --screenshot preview.png
```

The smoke runner creates a temporary, local-only mailbox with sample messages,
a long HTML body and attachments. It launches a separate headless Thunderbird,
checks the actual interface and uses a loopback server to verify image loading.
It does not open the normal mail profile or send messages.

The checks cover clean startup, conversation expansion, keyboard focus, attachment
placement and menus, reading margins, body size, dropdown spacing, the scroll
gutter, list-icon placement, All/Unread filtering, image loading and repeated
reloads without missing initials or duplicate controls.

A full Thunderbird/Firefox source build and upstream mochitests have not been run
for this standalone customization package. The profile setup/restore path is also
checked against a temporary configuration so unrelated settings remain intact.

## Maintenance

Keep changes in this directory on the fork's `outlook-layout` branch. It is
independent of upstream Thunderbird source files and build configuration.

The extension adapts the native conversation component and uses Thunderbird
internal UI APIs. Future Thunderbird releases can require adjustments; repeat
the smoke checks before upgrading the supported version. Current limitations
include conversations being assembled from the selected folder's thread, rather
than merging all folders, and no Outlook Focused Inbox classifier.

The stylesheet targets existing Thunderbird element IDs because it is installed
as a profile override. Extension-owned strings live in `_locales/en/messages.json`.
Native account, message and attachment strings retain Thunderbird localization.

Code is licensed under MPL-2.0; see [LICENSE](LICENSE). Thunderbird's existing
icons and message components retain their upstream licences. The mountain-lake
wallpaper is an original generated asset; its production prompt is recorded in
[ASSET-NOTES.txt](ASSET-NOTES.txt).

## Local sender photos

Store an email-to-image mapping in `chrome/avatars.json` inside the Thunderbird
profile. Each value must be a PNG or JPEG data URI, for example:

```json
{"sender@example.test": "data:image/png;base64,..."}
```

Use lowercase email addresses and base64-encoded image bytes (under 2 MB per
entry). Restart Thunderbird after changing this file. Photos appear in message
headers, conversation summaries and message-list cards; other senders keep their
initials. This file belongs to the profile and must not be committed with account
data. No Microsoft credentials or remote photo service are required.
