# VCollab for Claude

Work with engineering simulation results from a conversation. This plugin connects Claude to the
VCollab installation on your Windows computer, so Claude can inspect native CAE, CAD and JT files,
convert them to VCollab's compact CAX format, merge CAX files, render result images, and run VCollab
Pro XML batch jobs. Everything runs locally against files you name; nothing is uploaded by the
plugin.

It also adds two skills: a workflow guide for using the VCollab tools, and a CAE result-review
skill that helps Claude interpret stress, deformation, CFD, and mesh-quality results.

## Requirements

- Windows 10 or 11.
- **VCollab 26.1 or later**, installed and licensed. The plugin drives VCollab's own command-line
  programs; it does not include them. CST and Adams conversions also need a CST or MSC Adams license.
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** on your `PATH`. The plugin uses
  it to start its Python server.
- Claude Code, or Cowork sessions that run on your computer. Claude chat on the web does not run
  local servers, so the tools are unavailable there (the skills still load).

## Install

Add **VCollab** from the plugin directory in Claude (**Customize > Plugins**), or in Claude Code
run `/plugin` and search for VCollab.

To install straight from this repository in Claude Code (2.1.275 or later):

```
/plugin install vcollab --marketplace vcollab/vct-marketplace
```

The first start takes a minute: uv downloads Python 3.12 and the server's pinned dependencies.
Later starts are fast.

### Settings

Both settings are optional. Claude Code asks for them when you enable the plugin; in Cowork the
defaults apply.

| Setting | Default | Use it when |
|---|---|---|
| VCollab installation folder | Auto-detected (newest `C:\Program Files\VCollab\<version>`) | VCollab is installed somewhere else |
| Allowed folders | Empty (any path you name) | You want the tools confined to certain folders. Separate folders with `;` |

## Tools

| Tool | What it does | Changes files |
|---|---|---|
| `vcollab_caxinfo` | Reads a CAX file's parts, results, instances, and history | No |
| `vcollab_caeinfo` | Reads a native CAE file's model info and available results | No |
| `vcollab_cadinfo` | Reads CAD mass properties (mass, volume, CG, inertia) | No |
| `vcollab_vmovecaevalidate` | Checks a VMoveCAE command file without translating | No |
| `vcollab_health` | Reports the detected VCollab install and settings | No |
| `vcollab_vmovecae` | Converts Ansys, Nastran, LS-DYNA, Abaqus, or Fluent results to CAX | Writes a `.cax` |
| `vcollab_vmovex` | Converts CFD and other formats (CGNS, EnSight, OpenFOAM, VTK) to CAX | Writes a `.cax` |
| `vcollab_vmovecad` | Converts CATIA, STEP, IGES, or Pro/E CAD to CAX | Writes a `.cax` |
| `vcollab_vmovejt` | Converts a JT file to CAX | Writes a `.cax` |
| `vcollab_vmovecst` | Converts a CST Studio result to CAX | Writes a `.cax` |
| `vcollab_vmoveadams` | Converts an MSC Adams result to CAX | Writes a `.cax` |
| `vcollab_vmovecaesubmit` | Runs a VMoveCAE command file (multi-file translations) | Writes the files it names |
| `vcollab_caxmerge` | Merges CAX files, or a CAX and a viewpoint file | Writes a `.cax` |
| `vcollab_image_generator` | Renders a CAX model to PNG, JPG, BMP, TIFF, or PDF | Writes an image |
| `vcollab_vcollabpro` | Runs a VCollab Pro XML batch job (images, merges, viewpoint slides) | Writes the files it names |

Tools that write files are marked destructive, so Claude asks before each call. A failed run never
replaces an existing output file. `vcollab_vcollabpro` accepts declarative XML only; this plugin
cannot run scripts.

## Example prompts

1. "What results and load steps are in `D:\sims\bracket\bracket.rst`?"
2. "Convert `D:\sims\bracket\bracket.rst` to CAX with only Displacement and Stress, then render
   an isometric PNG colored by von Mises stress."
3. "Merge `D:\sims\run1.cax` and `D:\sims\run2.cax` into `D:\sims\compare.cax`."
4. "Check my command file `D:\jobs\fatigue_inputs.txt` and run it if it's valid."
5. "Review this stress result: is the peak at the fillet a real hotspot or a singularity?"

## What runs and what it connects to

- **Local programs.** The tools start VCollab executables from your VCollab install folder, with
  the file paths you give. They read the inputs you name and write outputs where you say.
- **Package downloads.** On first start, uv downloads a Python runtime (from the python-build-standalone
  project on GitHub) and the exact package versions pinned in `uv.lock` (from PyPI). It keeps them
  in the plugin's data folder.
- **No other network access.** The server sends nothing to VCollab or any third party.
- **Your conversation.** Like every Claude tool, the paths you give and the results the tools
  return become part of your Claude conversation.

## Privacy Policy

The plugin collects no personal data and sends nothing to VCollab or third parties. It writes a
local log of startup status and errors to `%LOCALAPPDATA%\VCollab\mcp\logs` (five files of at most
1 MB each, oldest deleted first). The full policy is in [PRIVACY.md](https://github.com/vcollab/vct-marketplace/blob/main/plugins/vcollab-plugin/PRIVACY.md).

## Troubleshooting

- **"VCollab installation not found" or a missing executable.** Ask Claude to run `vcollab_health`.
  If the folder is wrong, set **VCollab installation folder** in the plugin settings.
- **The server doesn't start.** Run `uv --version` in a terminal. If uv is missing, install it and
  restart Claude.
- **"Path is outside the allowed roots".** The file is outside the folders in **Allowed folders**.
  Add its folder or clear the setting.
- **A conversion reports no output.** Check that the file opens in VCollab, and that any result or
  part names you filtered by exist (ask Claude to list them first).

## Support

Report problems at https://github.com/vcollab/vct-marketplace/issues or email srinivasamurthi@vcollab.com.

## License

MIT. See [LICENSE](LICENSE). VCollab itself is commercial software licensed separately.
