---
name: vcollab-workflows
description: Use when the user wants to inspect, convert, merge, render, or batch-process engineering simulation files with their local VCollab install, for example "convert this .rst / .op2 / .odb / d3plot to CAX", "what results are in this .cax", "render an image of the model", "merge these CAX files", or any mention of VCollab, CAX, VMoveCAE, or VCollab Pro.
---

# Working with VCollab files

The VCollab tools run the user's own VCollab 26.1+ installation on Windows. Every tool works on
explicit file paths on the user's machine. Nothing is uploaded anywhere by the tools.

## Before the first call

- Ask for **full absolute paths** (for example `D:\models\bracket.rst`). A relative path resolves
  against the server's working directory, which is usually not the user's project folder.
- If a tool reports that VCollab or an executable was not found, call `vcollab_health`. It shows the
  detected install folder and which executables resolved. The fix is almost always setting the
  plugin's **VCollab installation folder** option.

## Pick the tool from the file type

| User has | Goal | Tool |
|---|---|---|
| `.cax` | See parts, results, instances, history | `vcollab_caxinfo` |
| Native CAE result (`.rst`, `.rth`, `.op2`, `.odb`, `d3plot`, Fluent `.cas`/`.dat`) | See what it contains | `vcollab_caeinfo` |
| Native CAE result | Convert to CAX | `vcollab_vmovecae` |
| CFD or other formats (CGNS, EnSight, OpenFOAM, VTK, Converge) | Convert to CAX | `vcollab_vmovex` |
| CAD (`.CATPart`, `.CATProduct`, STEP, IGES, Pro/E) | Mass properties | `vcollab_cadinfo` |
| CAD | Convert to CAX | `vcollab_vmovecad` |
| `.jt` | Convert to CAX | `vcollab_vmovejt` |
| CST `.gex` (with its whole Result folder) | Convert to CAX | `vcollab_vmovecst` |
| Adams `.adm` + `.res` | Convert to CAX | `vcollab_vmoveadams` |
| Several `.cax` files, or a `.cax` plus a `.vpt` | One merged CAX | `vcollab_caxmerge` |
| `.cax` | A PNG/JPG/PDF picture | `vcollab_image_generator` |
| `.cax` | Images, merges, or viewpoint slides from one job | `vcollab_vcollabpro` (XML) |

CST needs a CST license and Adams needs an MSC Adams license on the machine. Mention this if
either conversion fails.

## Common flows

**Result file to picture.** Inspect with `vcollab_caeinfo` to learn the exact result names, convert
with `vcollab_vmovecae` (pass `results` to keep only what the user needs; large models convert much
faster), then render with `vcollab_image_generator`. To color by a result, pass its exact name from
`vcollab_caxinfo`, for example `result="Stress"` and `derived="Von Mises Stress"`.

**Multi-file translation.** When the user needs a base model plus extra result files (FEMFAT
`.dma`, CSV, NPZ), write a VMoveCAE command file, check it with `vcollab_vmovecaevalidate`, and run
it with `vcollab_vmovecaesubmit`. A minimal command file:

```text
* FILES
- model.odb, TYPE = ABAQUS_ODB, CONTENT = MODEL, RESULTS
- fatigue.dma, TYPE = FEMFAT_DMA, CONTENT = RESULTS
- model.cax, TYPE = VCOLLAB_CAX
```

`valid: false` from the validator is a normal answer about the file, not a tool failure. Show the
user the `report` text.

**Batch report job.** `vcollab_vcollabpro` runs a VCollab Pro XML batch. Image of a saved view:

```xml
<VCollabBatch sInputFile="D:/models/bracket.cax">
  <ImageGenerator ENABLE="TRUE" iImageWidth="1280" iImageHeight="720"
                  sOutPutImageFile="D:/models/bracket_iso.png"/>
  <SelectViewPoint ENABLE="TRUE" sViewPointName="Isometric" sViewPathName="Std.Views"/>
</VCollabBatch>
```

Merge as a new dataset:

```xml
<VCollabBatch sInputFile="D:/models/a.cax">
  <Output sOutputFile="D:/models/merged.cax"/>
  <MergeAsNewDataSet ENABLE="TRUE" sInputMergeCaxFile="D:/models/b.cax" iMergePosition="2"/>
</VCollabBatch>
```

Use plain double-quoted paths. The tool refuses XML with DOCTYPE or ENTITY declarations.

## Writing files safely

Converters, merge, image rendering, command-file runs, and XML batches create or overwrite files.
Default outputs land next to the input with a `.cax` extension. If the user hasn't named an output
and a file of that name may already exist, confirm before overwriting. A failed run never replaces
an existing good output.

## Reading the results

- VCollab executables often exit 0 even when they fail, so the tools judge success by a non-empty
  output file. When a result says `translated: false` or "success marker was not found", tell the
  user the output may be incomplete.
- Error messages carry the executable's own console text. Quote the relevant line rather than
  guessing at the cause.
- For engineering interpretation of the results themselves (stress levels, mesh quality,
  convergence), the `cae-expert` skill applies.
