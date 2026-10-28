# Privacy Policy: VCollab plugin for Claude

Effective 2026-10-27. Applies to version 0.2.0 and later of the VCollab plugin.

## Data collection

The plugin collects no personal data. It has no accounts, no analytics, and no telemetry.

When you ask Claude to use a tool, the plugin receives the arguments for that call (file paths and
options) and reads the files you name. It uses them only to run the requested VCollab program on
your computer.

## Use and storage

- Files are processed locally by VCollab programs on your computer. Outputs are written to the
  paths you choose.
- The plugin keeps a local log at `%LOCALAPPDATA%\VCollab\mcp\logs\vcollab-mcp.log`. It records
  startup status (detected VCollab folder, which executables were found) and errors. Error
  entries can include file paths. File contents are never logged.
- On first start, uv stores a Python runtime and the plugin's dependencies in the plugin's data
  folder on your computer.

## Third-party sharing

The plugin sends no data to VCollab or any third party.

Two transfers happen outside the plugin's own code:

- **Package downloads.** uv downloads Python (from the python-build-standalone project on GitHub)
  and pinned packages (from PyPI). These are ordinary downloads; no information about you or your
  files is sent beyond what any download involves, such as your IP address.
- **Your Claude conversation.** Tool arguments and results become part of your conversation with
  Claude and are handled under Anthropic's privacy policy.

## Data retention

The log rotates at 1 MB and keeps at most five files; the oldest is deleted first. You can delete
the log folder at any time. Uninstalling the plugin removes its data folder. The plugin keeps no
other data.

## Contact

Questions about this policy: srinivasamurthi@vcollab.com, or open an issue at https://github.com/vcollab/vct-marketplace/issues.
