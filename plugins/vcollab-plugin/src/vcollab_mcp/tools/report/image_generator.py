"""``image_generator`` — render a VCollab CAX file to a static image via VCollabImageGenerator.

``VCollabImageGenerator.exe`` (in ``VCollabProX``) is a renderer: it opens a ``.cax`` model,
positions a standard camera, optionally colors the model by a chosen result, and writes a single
image file. It is how a CAX is turned into a shareable picture (report figure, thumbnail, preview).

Two facts verified against the real exe drive this wrapper:

* It is a **GUI** application. Run bare it pops a usage dialog and would block a server; passing
  ``-swrend`` (software renderer) as the FIRST argument makes it run **headless** — no window. We
  always pass ``-swrend``.
* On success it exits 0 and writes the image; on a bad input it exits non-zero and writes nothing.
  Even so, output is verified the safe way (write to a temp, promote only a non-empty result via
  :func:`produce_output`) so a prior image is never clobbered by a failed run.

This wrapper implements **Usage #1 (single image)**. The exe also has a ``-v`` multi-image batch
mode (one image per saved viewpoint in a ``.vpt`` file, or per CAE result); that mode is not
exposed here.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, Field

from ...paths import PathPolicy
from ...process import run_executable
from ...settings import Settings
from .._output import produce_output

# Standard cameras combined with display modes, accepted by the exe's view parameter.
_BASE_VIEWS = ("Front", "Rear", "Top", "Bottom", "Left", "Right", "Iso")
_VIEW_MODES = ("", "Mesh", "Wire", "HiddenLine")
# Map each lowercased form to its canonical spelling so callers can pass any case.
_VALID_VIEWS: dict[str, str] = {
    f"{base}{mode}".lower(): f"{base}{mode}" for base in _BASE_VIEWS for mode in _VIEW_MODES
}

# Output formats the exe supports (chosen by the output file's extension). 'jpeg'/'tiff' are
# accepted as friendly aliases of the documented 'jpg'/'tif'.
_SUPPORTED_FORMATS = frozenset({"png", "jpg", "jpeg", "bmp", "tif", "tiff", "pdf", "jt", "wcax"})


class ImageResult(BaseModel):
    """Outcome of rendering a CAX file to an image."""

    input_file: str = Field(description="The CAX file that was rendered.")
    output_file: str = Field(description="Name of the image written.")
    output_path: str = Field(description="Absolute path of the image written.")
    size_bytes: int
    image_format: str = Field(description="Image format, from the output extension (e.g. 'png').")
    view: str = Field(description="The camera/display view used (e.g. 'Iso', 'FrontWire').")
    width: int
    height: int
    result: str = Field(default="", description="Result the model was colored by ('' = default).")
    message: str


def image_generator(
    input_path: str,
    output_path: str,
    *,
    view: str = "Iso",
    width: int = 600,
    height: int = 500,
    legend: bool = True,
    result: str = "",
    instance: str = "",
    derived: str = "",
    background: list[float] | None = None,
    settings: Settings,
    paths: PathPolicy,
) -> ImageResult:
    """Render ``input_path`` (a CAX file) to ``output_path`` (an image).

    Args:
        input_path: Source .cax file (e.g. 'bracket.cax').
        output_path: Image to write; the format comes from its extension
            (png/jpg/jpeg/bmp/tif/tiff/pdf/jt/wcax), e.g. 'bracket.png'.
        view: Camera + display mode. Base view Front/Rear/Top/Bottom/Left/Right/Iso, optionally
            suffixed Mesh/Wire/HiddenLine (e.g. 'Iso', 'FrontWire', 'TopMesh'). Default 'Iso'.
        width: Image width in pixels (default 600).
        height: Image height in pixels (default 500).
        legend: Show the result color legend (default True).
        result: Result name to color the model by (default: first result in the cax).
        instance: Instance/step name for that result (default: first instance).
        derived: Derived component (e.g. 'Von Mises Stress', 'Translational Magnitude'); default
            depends on the result's data type. To set this, also set ``result``/``instance``.
        background: Background color as [r, g, b] each 0-1 (default white [1,1,1]); a channel > 1
            makes the background transparent in formats that support it.

    Raises:
        ValueError: on an unknown view, unsupported output format, non-positive size, bad
            background, or an output that equals the input.
        PathError: if a path is outside the allowed roots.
        FileNotFoundError: if the input file does not exist.
        ProcessError: if the renderer runs but produces no image.
    """
    if width < 1 or height < 1:
        raise ValueError(f"width and height must be >= 1 (got {width}x{height}).")

    canonical_view = _VALID_VIEWS.get(view.strip().lower())
    if canonical_view is None:
        raise ValueError(
            f"Unknown view {view!r}. Use one of Front/Rear/Top/Bottom/Left/Right/Iso, "
            "optionally suffixed with Mesh, Wire, or HiddenLine (e.g. 'Iso', 'FrontWire')."
        )

    resolved_input = paths.resolve_input(input_path)
    resolved_output = paths.resolve_output(output_path)
    if resolved_output == resolved_input:
        raise ValueError("output_path must differ from the input file.")

    image_format = resolved_output.suffix.lstrip(".").lower()
    if image_format not in _SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported image format {image_format or '(none)'!r} for {output_path!r}. "
            "Supported: png, jpg (or jpeg), bmp, tif (or tiff), pdf, jt, wcax."
        )

    bg = background if background is not None else [1.0, 1.0, 1.0]
    if len(bg) != 3:
        raise ValueError(f"background must be 3 numbers [r, g, b], got {len(bg)}.")
    # The exe documents each channel as 0-1 (a color), with > 1 meaning "transparent". Negative,
    # NaN, and infinite values are outside that contract — reject them so a clear error is returned
    # rather than silently passing 'nan'/'-0.5' to the renderer (which produces an undefined color).
    if any(not math.isfinite(c) or c < 0 for c in bg):
        raise ValueError(
            "background channels must be finite and >= 0 "
            "(0-1 is a color; a value > 1 requests a transparent background)."
        )

    # Optional positional params, in the documented order (they 'must be in the same order').
    # The full argv is: -swrend <input> <output> <width> <height> <view> <bgR> <bgG> <bgB> <legend>
    #                   [<result> [<instance> [<derived>]]]
    optional_args = [
        str(width),
        str(height),
        canonical_view,
        str(bg[0]),
        str(bg[1]),
        str(bg[2]),
        "LegendON" if legend else "LegendOFF",
    ]
    # The result/instance/derived trio is positional: to reach a later one, the earlier slots must
    # be present (empty = exe default). Include the chain only up to its last specified value;
    # if none are set, omit it entirely so the exe uses its own defaults (first result, etc.).
    chain = [result, instance, derived]
    last_set = max((i for i, v in enumerate(chain) if v), default=-1)
    optional_args.extend(chain[: last_set + 1])

    exe = settings.resolve_executable("vcollabimggen")
    produce_output(
        resolved_output,
        lambda out: run_executable(
            exe,
            ["-swrend", str(resolved_input), str(out), *optional_args],
            timeout=settings.timeout_for("image_generator"),
            env=settings.subprocess_env(),
        ),
        error_message=(
            f"VCollabImageGenerator produced no image for {resolved_input.name!r}. Check that it "
            "is a valid CAX file and that the result/instance names (if given) exist in it."
        ),
    )

    return ImageResult(
        input_file=resolved_input.name,
        output_file=resolved_output.name,
        output_path=str(resolved_output),
        size_bytes=resolved_output.stat().st_size,
        image_format=image_format,
        view=canonical_view,
        width=width,
        height=height,
        result=result,
        message=(
            f"Rendered {resolved_input.name} to {resolved_output.name} "
            f"({canonical_view} view, {width}x{height})."
        ),
    )
