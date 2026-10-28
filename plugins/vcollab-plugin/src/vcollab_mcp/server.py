"""FastMCP server assembly.

``create_server`` builds a fully-wired :class:`FastMCP` instance with its dependencies
(settings + path policy) injected, so tests can construct an isolated server pointed at any
allowed-roots configuration without touching global state.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from .coercion import FloatList, RequiredStrList, StrList
from .diagnostics import HealthReport, build_health_report
from .logging_config import get_logger
from .process import ProcessError
from .settings import Settings, get_settings
from .tools.info.cadinfo import CadInfoResult, cadinfo
from .tools.info.caeinfo import CaeInfoResult, caeinfo
from .tools.info.caxinfo import CaxInfoResult, caxinfo
from .tools.knowledge.cae_expert import CaeExpertKnowledge, cae_expert
from .tools.knowledge.python_api import VCollabApiAnswer, python_api
from .tools.merge.caxmerge import CaxMergeResult, caxmerge
from .tools.report.image_generator import ImageResult, image_generator
from .tools.report.vcollabpro import VCollabProResult, vcollabpro
from .tools.translate.vmoveadams import VMoveAdamsResult, vmoveadams
from .tools.translate.vmovecad import VMoveCadResult, vmovecad
from .tools.translate.vmovecae import VMoveCaeResult, vmovecae
from .tools.translate.vmovecaesubmit import VMoveCaeSubmitResult, vmovecaesubmit
from .tools.translate.vmovecst import VMoveCstResult, vmovecst
from .tools.translate.vmovejt import VMoveJtResult, vmovejt
from .tools.translate.vmovex import VMoveXResult, vmovex
from .tools.validate.vmovecaevalidate import VMoveCaeValidateResult, vmovecaevalidate

logger = get_logger(__name__)

INSTRUCTIONS = """\
VCollab MCP server. Tools operate on CAE/CAX engineering files by explicit path (absolute, or
relative to the server's working directory). Pass an input path and, for tools that write, an
output path. Use `vcollab_caxinfo` to inspect a .cax file's metadata, and `vcollab_health` to
confirm the VCollab install is detected and see the file-access policy.
"""

# "full": every tool (pip wheel, portable zip, .mcpb). "plugin": the build listed in Anthropic's
# plugin directory — no arbitrary-code path and no knowledge tools (see create_server).
EDITIONS = ("full", "plugin")


def log_startup_summary(settings: Settings) -> HealthReport:
    """Probe the install at startup and log a one-line readiness summary."""
    report = build_health_report(settings, log_file=str(settings.log_file()))
    found = sum(1 for e in report.executables if e.found)
    total = len(report.executables)
    if report.all_required_present:
        logger.info(
            "VCollab MCP ready: vcollab_dir=%s, %d/%d executables resolved, file_access=%s",
            report.vcollab_dir, found, total, report.file_access,
        )
    else:
        missing = [e.name for e in report.executables if not e.found]
        logger.warning(
            "VCollab MCP starting DEGRADED: %d/%d executables resolved (missing: %s). "
            "Executable-backed tools will return errors until VCOLLAB_DIR is correct. "
            "Run `vcollab-mcp doctor` to diagnose.",
            found, total, ", ".join(missing) or "?",
        )
    return report


def create_server(settings: Settings | None = None, *, edition: str = "full") -> FastMCP:
    """Create and configure the VCollab FastMCP server.

    ``edition`` selects the tool set (see :data:`EDITIONS`). The ``"plugin"`` edition is what the
    Claude directory plugin runs: ``vcollab_vcollabpro`` accepts XML batch jobs only (the Python
    opt-in is forced off as well), and the two knowledge tools are omitted because the plugin
    ships that reference material as native skills.
    """
    if edition not in EDITIONS:
        raise ValueError(f"edition must be one of {EDITIONS}, got {edition!r}.")
    settings = settings or get_settings()
    if edition == "plugin":
        settings = settings.model_copy(update={"enable_vcollabpro_script": False})
    paths = settings.path_policy()

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[None]:
        # Startup validation: report (but never fail on) a missing/incomplete install.
        try:
            log_startup_summary(settings)
        except Exception:  # startup diagnostics must not take the server down
            logger.exception("Startup validation failed unexpectedly; continuing.")
        yield

    # mask_error_details: unexpected exceptions are returned to the client as a generic
    # message instead of a stack trace; ToolError messages still pass through verbatim.
    mcp: FastMCP = FastMCP(
        name="vcollab",
        instructions=INSTRUCTIONS,
        lifespan=lifespan,
        mask_error_details=True,
    )

    def tool(group: str, title: str, *, writes: bool, idempotent: bool = True, name: str = ""):
        """Register a tool under its MCP tag, with the annotations Claude's directory requires.

        ``writes`` marks tools that create or overwrite files: they are flagged destructive, so
        clients confirm each call. Every other tool is read-only. All tools are closed-world —
        they touch only local files and the local VCollab install.
        """
        return mcp.tool(
            name=name or None,
            tags={group},
            title=title,
            annotations=ToolAnnotations(
                title=title,
                readOnlyHint=not writes,
                destructiveHint=writes,
                idempotentHint=idempotent,
                openWorldHint=False,
            ),
        )

    @tool("info", "Read CAX File Metadata", writes=False)
    def vcollab_caxinfo(input_path: str) -> CaxInfoResult:
        """Extract metadata from a VCollab CAX file.

        Returns the source model, analysis category, file sizes, counts, and the lists of
        parts, results, and instances contained in the file.

        Args:
            input_path: Path to the .cax file (e.g. 'bracket.cax' or 'D:/data/bracket.cax').
        """
        try:
            return caxinfo(input_path, settings=settings, paths=paths)
        except ProcessError as exc:
            raise ToolError(f"CaxInfo failed: {exc}") from exc
        except (ValueError, OSError, KeyError) as exc:
            # ValueError covers PathError (out-of-bounds); OSError covers FileNotFoundError.
            raise ToolError(str(exc)) from exc

    @tool("info", "Read CAE Model Metadata", writes=False)
    def vcollab_caeinfo(input_path: str, results_path: str = "") -> CaeInfoResult:
        """Extract metadata from a native CAE file (Ansys .rst, Nastran .op2, LS-DYNA d3plot,
        Fluent .cas/.dat, Abaqus .odb, etc.).

        Returns the model info, the list of available results/datasets (with data type, entity
        type, and counts), a headline summary (nodes/elements/materials when present), and the
        solver-specific sections (parts, zones, constraints, materials, ...).

        Args:
            input_path: Path to the model file (e.g. 'beam.rst', 'd3plot', 'model.cas').
            results_path: Optional separate results file, when the solver splits model and
                results (e.g. a Fluent '.dat' paired with a '.cas'). Leave empty otherwise.
        """
        try:
            return caeinfo(input_path, results_path, settings=settings, paths=paths)
        except ProcessError as exc:
            raise ToolError(f"CaeInfo failed: {exc}") from exc
        except (ValueError, OSError, KeyError) as exc:
            raise ToolError(str(exc)) from exc

    @tool("info", "Read CAD Mass Properties", writes=False)
    def vcollab_cadinfo(input_path: str) -> CadInfoResult:
        """Extract metadata from a native CAD file (CATIA .CATPart/.CATProduct, Pro/E, STEP,
        IGES, ...).

        Returns the authoring CAD package and units, plus per-part mass properties: density,
        volume, mass, weight, surface area, center of gravity, and the inertia tensor.

        Args:
            input_path: Path to the CAD file (e.g. 'Part2.CATPart').
        """
        try:
            return cadinfo(input_path, settings=settings, paths=paths)
        except ProcessError as exc:
            raise ToolError(f"CadInfo failed: {exc}") from exc
        except (ValueError, OSError, KeyError) as exc:
            raise ToolError(str(exc)) from exc

    @tool("merge", "Merge CAX Files", writes=True)
    def vcollab_caxmerge(input_paths: RequiredStrList, output_path: str) -> CaxMergeResult:
        """Merge multiple CAX files (or a CAX plus a .vpt viewpoint file) into one CAX.

        Examples: merge several result files into a multi-model CAX, or bake a viewpoint (.vpt)
        file into a CAX.

        Args:
            input_paths: Two or more file paths to merge, in order (e.g.
                ['bracket.cax', 'beam.cax'] or ['bracket.cax', 'views.vpt']).
            output_path: Path of the merged CAX to write (e.g. 'merged.cax').
        """
        try:
            return caxmerge(input_paths, output_path, settings=settings, paths=paths)
        except ProcessError as exc:
            raise ToolError(f"CaxMerge failed: {exc}") from exc
        except (ValueError, OSError, KeyError) as exc:
            # ValueError covers too-few-inputs and PathError; OSError covers a missing input file.
            raise ToolError(str(exc)) from exc

    @tool("translate", "Convert CAE Results to CAX", writes=True)
    def vcollab_vmovecae(
        input_path: str,
        output_path: str = "",
        results_path: str = "",
        results: StrList = None,
        filter_results: StrList = None,
        nodal_results: StrList = None,
        element_results: StrList = None,
        default_element_results: bool = False,
        sections: StrList = None,
        parts: StrList = None,
        filter_parts: StrList = None,
        part_ids: StrList = None,
        filter_part_ids: StrList = None,
        instances: StrList = None,
        filter_instances: StrList = None,
        cut_sections: StrList = None,
        iso_surfaces: StrList = None,
        flow_lines: StrList = None,
        part_grouping: str = "",
        model_file_format: str = "",
        enable_mid_nodes: bool = False,
        enable_input_files_caching: bool = False,
        enable_odb_fast_load: bool = False,
        enable_odb_load_zero_frames: bool = False,
        no_averaging_across_materials: bool = False,
        abaqus_input_file: str = "",
        ansys_input_commands: str = "",
        odb_version: str = "",
    ) -> VMoveCaeResult:
        """Convert a native CAE file to VCollab CAX format (the ingest step for other tools).

        This is the direct VMoveCAEBatch path: one native model file in, one .cax out, with optional
        filtering, result-property control, embedded geometry features, and load/translation
        toggles. Supports common solvers (Ansys .rst/.rth, Nastran .op2/.bdf, LS-DYNA d3plot, Abaqus
        .odb, Fluent .cas/.dat). Prefer this for ordinary and moderately advanced conversions.

        For a Fluent-style split model+results pair, pass the .dat as `results_path`. For jobs this
        tool STILL cannot express — overlaying MULTIPLE appendable result files (FEMFAT .dma,
        VCOLLAB_CSV, NUMPY_NPZ) onto a base model, or per-step/increment selection beyond the
        instance flags — use `vcollab_vmovecaesubmit` (command-file driven) instead.

        Filtering precedence (the exe's rules, mirror them when choosing args):
          - if both `results` and `filter_results` are given, `filter_results` is ignored;
          - if `parts` or `part_ids` is given, `filter_parts`/`filter_part_ids` are ignored.

        Result-property control: by default every result is written as nodal values. Use
        `element_results` to force specific results to elemental, `nodal_results` to force nodal,
        `default_element_results` to write all element-located results as elemental, and `sections`
        to pick shell sections. To pre-compute a derived type before averaging (e.g. matching
        Abaqus "compute scalars before averaging" for one quantity), name it in `results` with the
        `"<result> - <derived>"` form, e.g. results=['Stress - Von Mises'].

        Embedded features (baked into the .cax for the viewer): `cut_sections` are plane equations
        'AX+BY+CZ=D' (a single value or a 'start:end:count' range on the right side, e.g.
        'Y=0:10:5'); `iso_surfaces` are scalar result names (optionally with a derived type);
        `flow_lines` are CFD streamline specs '[result, seed_part_or_point, n_lines]'.

        Args:
            input_path: Source CAE model file path (e.g. 'beam.rst', 'model.op2', 'd3plot').
            output_path: Output .cax path; defaults to the input path with a .cax extension.
            results_path: Separate results file when the solver splits model+results (e.g. a Fluent
                '.dat' paired with a '.cas'). Leave empty otherwise.
            results: Only translate these result names (e.g. ['Displacement', 'Stress']).
            filter_results: Exclude these result names (ignored if `results` is given).
            nodal_results: Force these results to be written as nodal values.
            element_results: Force these results to be written as elemental values.
            default_element_results: Write all element-located results as elemental.
            sections: Shell sections to export — any of Top, Bottom, Mid, Maximum, Minimum, Average.
            parts: Only translate these part names.
            filter_parts: Exclude these part names (ignored if `parts`/`part_ids` is given).
            part_ids: Only translate parts with these IDs; ranges allowed (e.g. ['1', '30-35']).
            filter_part_ids: Exclude parts with these IDs (ignored if `parts`/`part_ids` is given).
            instances: Only translate these instances/ranges (e.g. ['1-6', '8-12']; Abaqus frames
                like '1:5-1:8' = frames 5-8 of step 1).
            filter_instances: Exclude these instances/ranges.
            cut_sections: Plane equations 'AX+BY+CZ=D' to embed as cut-sections.
            iso_surfaces: Scalar result names (optionally with a derived type) for ISO-surfaces.
            flow_lines: Flow-line specs '[result, seed_part_or_point, n_lines]' for CFD results.
            part_grouping: How elements are grouped into parts — one of: default, property-id,
                material-id, element-set, face-set, element-and-face-sets, element-type-number,
                no-parts, ansa-parts, hypermesh-components.
            model_file_format: Override the auto-detected input format (e.g. 'nastran_bdf',
                'ansys_rst', 'abaqus_odb', 'lsdyna_d3plot', 'fluent_cas').
            enable_mid_nodes: Include mid-nodes of higher-order elements (excluded by default).
            enable_input_files_caching: Cache remote/network inputs locally before processing.
            enable_odb_fast_load: ODB fast load — assumes all frames in a step share one result
                list (much faster; do NOT use if frames differ in their result lists).
            enable_odb_load_zero_frames: Include frame 0 (initial conditions) from ODB files.
            no_averaging_across_materials: Average nodal values only within a material region
                (preserves discontinuities; Ansys RST/RTH and Abaqus ODB only).
            abaqus_input_file: An Abaqus '.inp' to read element/face sets from (for an .odb input).
            ansys_input_commands: An Ansys 'ds.dat' to read named element selections from.
            odb_version: Abaqus ODB reader version as a year (e.g. '2024'), for .odb inputs.
        """
        try:
            return vmovecae(
                input_path,
                output_path,
                results_path=results_path,
                results=results,
                filter_results=filter_results,
                nodal_results=nodal_results,
                element_results=element_results,
                default_element_results=default_element_results,
                sections=sections,
                parts=parts,
                filter_parts=filter_parts,
                part_ids=part_ids,
                filter_part_ids=filter_part_ids,
                instances=instances,
                filter_instances=filter_instances,
                cut_sections=cut_sections,
                iso_surfaces=iso_surfaces,
                flow_lines=flow_lines,
                part_grouping=part_grouping,
                model_file_format=model_file_format,
                enable_mid_nodes=enable_mid_nodes,
                enable_input_files_caching=enable_input_files_caching,
                enable_odb_fast_load=enable_odb_fast_load,
                enable_odb_load_zero_frames=enable_odb_load_zero_frames,
                no_averaging_across_materials=no_averaging_across_materials,
                abaqus_input_file=abaqus_input_file,
                ansys_input_commands=ansys_input_commands,
                odb_version=odb_version,
                settings=settings,
                paths=paths,
            )
        except ProcessError as exc:
            raise ToolError(f"VMoveCAEBatch failed: {exc}") from exc
        except (ValueError, OSError, KeyError) as exc:
            raise ToolError(str(exc)) from exc

    @tool("translate", "Convert CAD to CAX", writes=True)
    def vcollab_vmovecad(input_path: str, output_path: str = "") -> VMoveCadResult:
        """Convert a native CAD file to VCollab CAX format (the CAD counterpart of vmovecae).

        Supports CATIA (.CATPart/.CATProduct), Pro/E, STEP, IGES, and other CAD formats.

        Args:
            input_path: Source CAD file path (e.g. 'Part2.CATPart', 'model.stp').
            output_path: Output .cax path; defaults to the input path with a .cax extension.
        """
        try:
            return vmovecad(input_path, output_path, settings=settings, paths=paths)
        except ProcessError as exc:
            raise ToolError(f"VMoveCADBatch failed: {exc}") from exc
        except (ValueError, OSError, KeyError) as exc:
            raise ToolError(str(exc)) from exc

    @tool("translate", "Convert JT to CAX", writes=True)
    def vcollab_vmovejt(input_path: str, output_path: str = "") -> VMoveJtResult:
        """Convert a Siemens JT file to VCollab CAX format.

        Args:
            input_path: Source JT file path (e.g. 'NX_Speedboat.jt').
            output_path: Output .cax path; defaults to the input path with a .cax extension.
        """
        try:
            return vmovejt(input_path, output_path, settings=settings, paths=paths)
        except ProcessError as exc:
            raise ToolError(f"VMoveJTBatch failed: {exc}") from exc
        except (ValueError, OSError, KeyError) as exc:
            raise ToolError(str(exc)) from exc

    @tool("translate", "Convert CFD or Multi-Solver File to CAX", writes=True)
    def vcollab_vmovex(
        input_path: str,
        output_path: str = "",
        results_path: str = "",
        odb_version: str = "",
    ) -> VMoveXResult:
        """Convert a CFD / multi-solver file to VCollab CAX using VMoveX.

        VMoveX is the broad translator: CGNS, EnSight, Fluent, OpenFOAM, Converge, VTK, and also
        Abaqus .odb / Ansys .rst/.rth / LS-DYNA d3plot and more.

        Args:
            input_path: Source file path (e.g. 'flow.cgns', 'case.foam', 'st1.vtk').
            output_path: Output .cax path; defaults to the input path with a .cax extension.
            results_path: Optional separate results file (e.g. a Fluent '.dat.h5').
            odb_version: Abaqus ODB reader version as a year (e.g. '2024'), for .odb inputs.
        """
        try:
            return vmovex(
                input_path,
                output_path,
                results_path=results_path,
                odb_version=odb_version,
                settings=settings,
                paths=paths,
            )
        except ProcessError as exc:
            raise ToolError(f"VMoveX failed: {exc}") from exc
        except (ValueError, OSError, KeyError) as exc:
            raise ToolError(str(exc)) from exc

    @tool("translate", "Convert CST Result to CAX", writes=True)
    def vcollab_vmovecst(input_path: str, output_path: str = "") -> VMoveCstResult:
        """Convert a CST (CST Studio electromagnetics) result to VCollab CAX.

        The .gex and ALL its sibling result files must sit together in the same folder (the whole
        CST 'Result' folder) — pointing at a lone .gex will fail. Requires a CST license at runtime.

        Args:
            input_path: Source .gex file path (e.g. 'model.gex').
            output_path: Output .cax path; defaults to the input path with a .cax extension.
        """
        try:
            return vmovecst(input_path, output_path, settings=settings, paths=paths)
        except ProcessError as exc:
            raise ToolError(f"VMoveCST failed: {exc}") from exc
        except (ValueError, OSError, KeyError) as exc:
            raise ToolError(str(exc)) from exc

    @tool("translate", "Convert Adams Result to CAX", writes=True)
    def vcollab_vmoveadams(
        adm_path: str, res_path: str, output_path: str = ""
    ) -> VMoveAdamsResult:
        """Convert an MSC Adams multibody-dynamics result to VCollab CAX.

        Requires an external MSC Adams Solver license (MSC_LICENSE_FILE), and the .adm's sibling
        .mtx/.mnf/.shl files must sit alongside it in the same folder.

        Args:
            adm_path: Source Adams model file path (e.g. 'crankshaft.adm').
            res_path: Source Adams results file path (e.g. 'crankshaft.res').
            output_path: Output .cax path; defaults to the .adm path with a .cax extension.
        """
        try:
            return vmoveadams(adm_path, res_path, output_path, settings=settings, paths=paths)
        except ProcessError as exc:
            raise ToolError(f"VMoveAdams failed: {exc}") from exc
        except (ValueError, OSError, KeyError) as exc:
            raise ToolError(str(exc)) from exc

    @tool("translate", "Run VMoveCAE Command File", writes=True)
    def vcollab_vmovecaesubmit(command_path: str) -> VMoveCaeSubmitResult:
        """Run a prepared VMoveCAE *command file* to translate CAE data to CAX (advanced jobs).

        This is the DECLARATIVE, command-file-driven alternative to `vcollab_vmovecae`. Both use
        the same engine and both produce a .cax, so for the COMMON case prefer `vcollab_vmovecae`
        — it converts one native file to one .cax with simple result/part/instance filters and
        needs no file authoring. Reach for `vcollab_vmovecaesubmit` ONLY when the job needs things
        `vcollab_vmovecae`'s flags cannot express:
          - combine MULTIPLE inputs — a base model plus appendable results (Fluent .dat, FEMFAT
            .dma, VCOLLAB_CSV, NUMPY_NPZ) overlaid onto it;
          - read entity/element sets from a SEPARATE model file (e.g. ABAQUS_INP with an .odb);
          - fine-grained PARTS / RESULTS / STEPS selection beyond the simple flags;
          - emit extra outputs (history .his, log .log) next to the .cax.

        The command file is a `.txt` in VMoveCAE's command-file format:
          - `*` begins a SECTION (FILES is mandatory; PARTS / RESULTS / STEPS are optional);
          - `-` is a DATA line: a bare file name first, then comma-separated `KEY=VALUE` attributes
            (an attribute value may itself be a comma-separated list);
          - `,` continues the previous line; any other line is a comment.
        Each FILES data line gives a file name, its `TYPE` (e.g. ANSYS_RST, ABAQUS_ODB, NASTRAN_OP2,
        LSDYNA_D3PLOT, FLUENT_CAS, FLUENT_DAT, FEMFAT_DMA, VCOLLAB_CSV — illustrative; a wrong token
        fails the run), and `CONTENT` (MODEL, RESULTS, ENTITY_SETS). Output = the `TYPE=VCOLLAB_CAX`
        line. Example:

            * FILES
            - model.odb, TYPE = ABAQUS_ODB, CONTENT = MODEL, RESULTS
            - fatigue.dma, TYPE = FEMFAT_DMA, CONTENT = RESULTS
            - model.cax, TYPE = VCOLLAB_CAX

        Files it references with relative names resolve next to the command file; every referenced
        path is checked against the allowed-roots policy. The run reports which .cax/.his/.log files
        it produced.

        Args:
            command_path: Path to the prepared .txt command file (e.g. 'inputs.txt').
        """
        try:
            return vmovecaesubmit(command_path, settings=settings, paths=paths)
        except ProcessError as exc:
            raise ToolError(f"VMoveCAESubmit failed: {exc}") from exc
        except (ValueError, OSError, KeyError) as exc:
            raise ToolError(str(exc)) from exc

    @tool("validate", "Validate VMoveCAE Command File", writes=False)
    def vcollab_vmovecaevalidate(command_path: str) -> VMoveCaeValidateResult:
        """Validate a VMoveCAE command file without translating it (a pre-flight check).

        A cheap pre-flight check for a hand-authored or complex command file of the kind
        `vcollab_vmovecaesubmit` runs: it confirms the required sections (FILES) are present,
        identifies each declared file's TYPE/CONTENT, and warns about referenced files that are
        missing — without running a (possibly long) translation and without producing a .cax.

        Returns `valid` (True if the file passed), `warnings` (advisories such as a missing
        referenced file — these do NOT fail validation), and `report` (the full check output). Note:
        `valid=False` is a normal result (the file is invalid), not an error.

        Args:
            command_path: Path to the .txt command file (e.g. 'inputs.txt'), in the same format
                `vcollab_vmovecaesubmit` consumes.
        """
        try:
            return vmovecaevalidate(command_path, settings=settings, paths=paths)
        except ProcessError as exc:
            raise ToolError(f"VMoveCAEValidate failed: {exc}") from exc
        except (ValueError, OSError, KeyError) as exc:
            raise ToolError(str(exc)) from exc

    @tool("report", "Render CAX to Image", writes=True)
    def vcollab_image_generator(
        input_path: str,
        output_path: str,
        view: str = "Iso",
        width: int = 600,
        height: int = 500,
        legend: bool = True,
        result: str = "",
        instance: str = "",
        derived: str = "",
        background: FloatList = None,
    ) -> ImageResult:
        """Render a VCollab CAX model to a static image with VCollabImageGenerator.

        Use this to turn a `.cax` into a picture: a report figure, a thumbnail/preview, or a
        result contour shot. It opens the model, sets a standard camera, optionally colors it by a
        result, and writes one image. It runs HEADLESS (no window). This is single-image rendering;
        it does NOT export interactive HTML/WCAX (use a scripting export for that), and it does not
        do the exe's multi-image `-v` viewpoint-batch mode.

        How the underlying exe is called (the verified contract):
            VCollabImageGenerator.exe -swrend <input.cax> <output.img> <width> <height> <view>
                <bgR> <bgG> <bgB> <LegendON|LegendOFF> [<result> [<instance> [<derived>]]]
        `-swrend` forces the software renderer so it never pops a window. All but input/output are
        optional and positional — to set a later one the earlier ones take their defaults.

        Output format is taken from `output_path`'s extension; supported: png, jpg (or jpeg),
        bmp, tif (or tiff), pdf, jt, wcax (e.g. 'bracket.png').

        Views (`view`): a base camera Front / Rear / Top / Bottom / Left / Right / Iso, optionally
        suffixed with a display mode Mesh, Wire, or HiddenLine — e.g. 'Iso' (shaded, default),
        'FrontWire', 'TopMesh', 'RightHiddenLine'.

        Coloring by a result: leave `result`/`instance`/`derived` empty to use the cax's first
        result and its natural default component. To color by a specific result, set `result` (and
        `instance` for the step), and optionally `derived` for the component (e.g. 'Von Mises
        Stress' for a tensor, 'Translational Magnitude' for a vector). `legend` toggles the color
        legend; `background` is [r, g, b] in 0-1 (default white), and a channel > 1 requests a
        transparent background in formats that support it.

        Args:
            input_path: Source .cax file path (e.g. 'bracket.cax').
            output_path: Image path to write; extension picks the format (e.g. 'bracket.png',
                'bracket_iso.jpg').
            view: Camera + display mode (default 'Iso'). See the view list above.
            width: Image width in pixels (default 600).
            height: Image height in pixels (default 500).
            legend: Show the result color legend (default True).
            result: Result name to color by (default: first result in the cax).
            instance: Instance/step for that result (default: first instance).
            derived: Derived component, e.g. 'Von Mises Stress' (default depends on data type).
            background: [r, g, b] each 0-1 (default white [1,1,1]); a channel > 1 = transparent.
        """
        try:
            return image_generator(
                input_path,
                output_path,
                view=view,
                width=width,
                height=height,
                legend=legend,
                result=result,
                instance=instance,
                derived=derived,
                background=background,
                settings=settings,
                paths=paths,
            )
        except ProcessError as exc:
            raise ToolError(f"VCollabImageGenerator failed: {exc}") from exc
        except (ValueError, OSError, KeyError) as exc:
            # ValueError covers bad view/format/size/background and PathError; OSError covers a
            # missing input file.
            raise ToolError(str(exc)) from exc

    @tool("report", "Run VCollab Pro Batch Job", writes=True, idempotent=False)
    def vcollab_vcollabpro(
        script: str = "",
        command_path: str = "",
        mode: str = "auto",
        input_paths: StrList = None,
        output_paths: StrList = None,
        description: str = "",
    ) -> VCollabProResult:
        """Drive VCollab Pro in batch mode: run a declarative XML job OR a Python automation script.

        This is the general-purpose VCollab Pro engine behind one tool. VCollab Pro's batch flag
        accepts two kinds of input, and this tool runs either (auto-detected):

        -- XML BATCH (always available, safe, declarative) --
        A `<VCollabBatch sInputFile="in.cax"> ... </VCollabBatch>` document with one or more enabled
        operation blocks. Supported operations:
          - ImageGenerator: `<ImageGenerator ENABLE="TRUE" iImageWidth=".." iImageHeight=".."
            sOutPutImageFile="out.png"/>` (+ optional `<SelectViewPoint ENABLE="TRUE"
            sViewPointName="Isometric" sViewPathName="Std.Views"/>`)
          - Merge: `<Output sOutputFile="merged.cax"/>` + `<MergeAsNewDataSet ENABLE="TRUE"
            sInputMergeCaxFile="b.cax" iMergePosition="2"/>`
          - Viewpoints to PowerPoint: `<ViewPoint2PPT ENABLE="TRUE" sOutputPPTPath="out.ppt"
            bUsePptTemplate="FALSE"/>`
          - Import viewpoints. Every file path the XML references is checked against the allowed-
            roots policy; relative paths resolve next to your declared output/input.

        -- PYTHON SCRIPT (opt-in; arbitrary `_VCollabAPI` code) --
        Disabled unless VCOLLAB_ENABLE_VCOLLABPRO_SCRIPT=1 (it executes arbitrary code inside
        VCollab Pro). Use it for anything the XML batch and the other tools can't do: probe values,
        create derived results, export HTML/WCAX (`xExportHTML`/`xExportWCax`), build viewpoints,
        report automation — the full ~1,178-function API (functions are `_VCollabAPI.x*()`, and
        `px*()` variants return Python lists). Key facts for writing a script:
          - DON'T GUESS the API. Before writing the script, call the `vcollab_python_api` tool to
            look up the exact function name, signature, parameters, and return type (e.g.
            `vcollab_python_api(query="xExportHTML")` or `query="find hotspot"`). Guessed
            signatures are the most common cause of a failed Python batch.
          - The module `_VCollabAPI` is pre-imported and available; Python 3 syntax.
          - Input CAX files passed in `input_paths` are AUTO-LOADED (first opened, second merged);
            get the loaded model with `_VCollabAPI.xGetCurCAEModelName()`.
          - To RETURN data, call `write_output(obj)` (a helper this tool injects for both inline
            and command-file scripts) — it lands in `output`. No other return channel exists.
          - Inline snippets get automatic error reporting; a complete command-file script should
            handle its own errors (a crash is still surfaced as missing expected outputs).
          - Do NOT call GUI/blocking functions (e.g. xMessageBox) — they are pointless in batch.
          - Runs headless; runs are timed out and the whole process tree is killed on timeout.

        Export to web — HTML / WCAX (verified recipe). To turn a CAX into a shareable, browser-
        viewable file: pass the source CAX in `input_paths` (it is AUTO-LOADED — do NOT xFileOpen
        it) and the target in `output_paths` (so the tool verifies it). Use forward slashes in the
        path string to avoid backslash-escaping:
            # input_paths=["D:/m/beam.cax"], output_paths=["D:/m/beam.html"]
            import _VCollabAPI
            _VCollabAPI.xFitView()                            # frame the scene (optional)
            ok = _VCollabAPI.xExportHTML("D:/m/beam.html", 0, False, False, "")
            write_output({"exported": bool(ok)})
          - `xExportHTML(path, iViewPoint, bThumbNail, bPassword, sPassword)` writes ONE
            self-contained WebGL `.html` (rotate/zoom/probe in any modern browser; ~MBs, no sidecar
            folder). `xExportWCax(...)` is IDENTICAL in signature and writes a `.wcax` for the
            VCollabWeb viewer. Pass iViewPoint=0 (current view), bThumbNail/bPassword=False,
            sPassword="". The returned bool is True on success.
          - To color by a result before exporting: `m = _VCollabAPI.xGetCurCAEModelName();
            _VCollabAPI.xSetCAEResult(m, "Displacement", "", "")` (then xFitView, then export).

        Note: VCollab Pro's batch exit code is ALWAYS 0, so success is judged by output files /
        write_output(), not the return code. To let the tool verify the run, give it something to
        check: list expected outputs in `output_paths`, and/or rely on auto-detected XML output
        attributes. The tool checks BOTH sources combined; if NEITHER yields a file, success is not
        verified (it reports what the console said).

        Args:
            script: Inline batch content — either XML or Python (auto-detected). REQUIRED: provide
                exactly one of `script` or `command_path` (not both, not neither).
            command_path: Path to a `.py` or `.xml` batch file. REQUIRED: provide exactly one of
                `script` or `command_path`.
            mode: 'auto' (default), 'python', or 'xml' to force the interpretation.
            input_paths: Up to two CAX file paths to auto-load (Python mode; XML declares its own
                input via sInputFile).
            output_paths: File paths the run is expected to produce, verified non-empty (used to
                confirm success since the exit code can't be trusted).
            description: Optional human note about the job's intent, echoed back in the result.
        """
        try:
            return vcollabpro(
                script,
                command_path,
                mode=mode,
                input_paths=input_paths,
                output_paths=output_paths,
                description=description,
                settings=settings,
                paths=paths,
            )
        except ProcessError as exc:
            raise ToolError(f"VCollabPro failed: {exc}") from exc
        except PermissionError as exc:
            # The Python path is gated off; surface the clear opt-in message.
            raise ToolError(str(exc)) from exc
        except (ValueError, OSError, KeyError) as exc:
            # ValueError: bad args/mode + PathError; OSError/FileNotFoundError: missing input/
            # command file; KeyError: misconfigured executable mapping.
            raise ToolError(str(exc)) from exc

    @tool("knowledge", "CAE Result Review Reference", writes=False)
    def vcollab_cae_expert(topic: str = "overview") -> CaeExpertKnowledge:
        """Senior CAE-engineer knowledge for reviewing and interpreting simulation results.

        Returns reference material (FEA/CFD/explicit-dynamics/contact/mesh/solver theory, a
        structured result-review protocol, and physics-based sanity checks) to ground answers about
        stress/strain/deformation/contact/thermal/modal results, mesh quality, convergence,
        singularities, and VCollab RRR / .cax / .wcax post-processing. Consult it before judging CAE
        results or writing an engineering review.

        Args:
            topic: 'overview' (the review protocol, behavioral rules, and image-analysis checklist),
                'domains' (per-discipline theory), 'postprocessing' (result-quantity interpretation
                and artifact detection), or 'all' (everything).
        """
        try:
            return cae_expert(topic)
        except (ValueError, OSError, KeyError) as exc:
            raise ToolError(str(exc)) from exc

    @tool("knowledge", "Look Up VCollab Python API", writes=False)
    def vcollab_python_api(query: str = "", section: str = "", limit: int = 20) -> VCollabApiAnswer:
        """Look up VCollab Pro `_VCollabAPI` functions before writing a `vcollab_vcollabpro` script.

        Searches the full reference (~1,178 functions) and returns each match's Python signature,
        description, return value, and section — so a Python batch script uses the exact, correct
        call instead of a guessed one.

        Args:
            query: A function name (e.g. 'xExportHTML') or a keyword/intent (e.g. 'export pdf',
                'hotspot', 'set cae result', 'deform scale'). Ranked best-match first.
            section: List a whole category instead of searching, e.g. 'CAE Probe',
                'File Operations', 'ViewPoint Operations'. (If both are given, section wins.)
            limit: Max results to return (default 20).

        With neither `query` nor `section`, returns the API usage guide (script template, type
        mapping, key rules) plus the list of all sections. Note: `px`-prefixed functions return
        Python lists; `x`-prefixed return bool/str/int.
        """
        try:
            return python_api(query=query, section=section, limit=limit)
        except (ValueError, OSError, KeyError) as exc:
            raise ToolError(str(exc)) from exc

    @tool("diagnostics", "Check VCollab Installation", writes=False)
    def vcollab_health() -> HealthReport:
        """Report server and VCollab installation status.

        Returns the detected VCollab directory, which executables resolved (with paths), the
        file-access policy (unrestricted, or the configured allowed roots), per-tool timeouts, and
        the log file location. Use this to confirm the server can reach VCollab before running
        other tools.
        """
        return build_health_report(settings, log_file=str(settings.log_file()))

    if edition == "plugin":
        # The directory plugin never exposes arbitrary code execution: drop the Python-capable
        # batch tool (and the API lookup that only serves it) and re-register an XML-only one
        # under the same name. The CAE reference ships as a native plugin skill instead.
        for removed in ("vcollab_vcollabpro", "vcollab_python_api", "vcollab_cae_expert"):
            mcp.local_provider.remove_tool(removed)

        @tool(
            "report",
            "Run VCollab Pro XML Batch Job",
            writes=True,
            idempotent=False,
            name="vcollab_vcollabpro",
        )
        def vcollab_vcollabpro_xml(
            xml: str = "",
            command_path: str = "",
            output_paths: StrList = None,
            description: str = "",
        ) -> VCollabProResult:
            """Run a declarative VCollab Pro XML batch job (VCollabPro.exe -b), headless.

            The job is a `<VCollabBatch sInputFile="in.cax"> ... </VCollabBatch>` document with
            one or more enabled operation blocks:
              - ImageGenerator: `<ImageGenerator ENABLE="TRUE" iImageWidth=".." iImageHeight=".."
                sOutPutImageFile="out.png"/>` (+ optional `<SelectViewPoint ENABLE="TRUE"
                sViewPointName="Isometric" sViewPathName="Std.Views"/>`)
              - Merge: `<Output sOutputFile="merged.cax"/>` + `<MergeAsNewDataSet ENABLE="TRUE"
                sInputMergeCaxFile="b.cax" iMergePosition="2"/>`
              - Viewpoints to PowerPoint: `<ViewPoint2PPT ENABLE="TRUE" sOutputPPTPath="out.ppt"
                bUsePptTemplate="FALSE"/>`
              - Import viewpoints.

            Only XML is accepted: this tool does not run Python scripts. The XML must be
            well-formed and must not contain DOCTYPE or ENTITY declarations. Every file path the
            XML references is checked against the allowed-roots policy; relative paths resolve
            next to the first declared output (else the command file).

            VCollab Pro's batch exit code is always 0, so success is judged by output files: the
            run fails if none of the outputs named in the XML (attributes containing 'Out') or in
            `output_paths` was written.

            Args:
                xml: Inline XML batch content. Provide exactly one of `xml` or `command_path`.
                command_path: Path to a `.xml` batch file. Provide exactly one of `xml` or
                    `command_path`.
                output_paths: Extra file paths the run is expected to produce, verified non-empty.
                description: Optional human note about the job's intent, echoed in the result.
            """
            try:
                return vcollabpro(
                    xml,
                    command_path,
                    mode="xml",
                    output_paths=output_paths,
                    description=description,
                    settings=settings,
                    paths=paths,
                )
            except ProcessError as exc:
                raise ToolError(f"VCollabPro failed: {exc}") from exc
            except (ValueError, OSError, KeyError) as exc:
                raise ToolError(str(exc)) from exc

    return mcp
