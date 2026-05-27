#!/usr/bin/env python3
"""Compose paper qualitative figure panels from a FocusParse demo bundle."""

from __future__ import annotations

import argparse
import csv
import json
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

DEFAULT_BUNDLE_DIR = Path("results/trace_viewer/paper-final-qualitative-assets")
DEFAULT_OUTPUT_DIR = Path("results/paper/qualitative-figure-panels")

CANVAS_W = 2400
CANVAS_H = 1600
MARGIN = 72

INK = (26, 32, 44)
MUTED = (92, 101, 116)
LINE = (207, 216, 228)
SURFACE = (246, 248, 251)
WHITE = (255, 255, 255)
BLUE = (37, 99, 235)
GREEN = (15, 118, 110)
AMBER = (180, 83, 9)


@dataclass(frozen=True)
class CropPick:
    """A single crop selected from the generated trace bundle."""

    page: int
    label: str
    role: str
    stage: str = "answer"
    kind: str = "citation"
    focus_box: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class FigureSpec:
    """Static paper figure recipe."""

    key: str
    filename: str
    example_id: str
    title: str
    subtitle: str
    claim: str
    picks: tuple[CropPick, ...]
    process: tuple[str, ...]


FIGURES = (
    FigureSpec(
        key="finance-latvia",
        filename="figure3-finance-latvia-evidence-binding.png",
        example_id="fin-bis_qr_2025_mar-0050",
        title="Finance evidence binding: charts + abbreviation table",
        subtitle="Prediction: Latvia | pages 8, 108, 109 | page recall 1.0 | BBox IoU 0.99999",
        claim=(
            "The answer requires binding two small chart-panel labels to the LV -> Latvia "
            "abbreviation table. Inspect builds readable regions; expand attaches the "
            "caption, footnote, and table context needed by the reasoner."
        ),
        picks=(
            CropPick(
                page=109,
                label="pkt_001",
                role="Panel B condition",
                stage="inspect",
                kind="selected",
            ),
            CropPick(
                page=108,
                label="pkt_004",
                role="Panel A condition",
                stage="inspect",
                kind="selected",
            ),
            CropPick(
                page=8,
                label="pkt_003",
                role="LV -> Latvia table row",
                stage="inspect",
                kind="selected",
                focus_box=(0.0, 0.55, 0.55, 0.68),
            ),
        ),
        process=("inspect_region", "expand_context", "answer", "verify"),
    ),
    FigureSpec(
        key="datasheet-jesd",
        filename="figure4-datasheet-jesd204b-evidence-binding.png",
        example_id="dat-JESD204B-Survival-Guide-0029",
        title="Datasheet evidence compaction: timing count + path corroboration",
        subtitle="Prediction: 6 | pages 16, 73 | page recall 1.0 | BBox IoU 0.99999",
        claim=(
            "The answer is a count in a dense timing diagram, but the prompt also "
            "requires cross-page corroboration from block diagrams. FocusParse turns "
            "the manual into a compact inspected-and-expanded packet set."
        ),
        picks=(
            CropPick(page=16, label="citation 1", role="K28.5 timing sequence"),
            CropPick(page=16, label="citation 2", role="ADC/JESD lane diagram"),
            CropPick(page=73, label="citation 3", role="Functional block diagram"),
        ),
        process=("inspect_region", "expand_context", "answer", "verify"),
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle-dir",
        type=Path,
        default=DEFAULT_BUNDLE_DIR,
        help="Static demo bundle produced by scripts/build_pipeline_demo.py.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for composed PNG panels and inventory files.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data = load_demo_data(args.bundle_dir)
    examples = {example["id"]: example for example in data["examples"]}
    args.output_dir.mkdir(parents=True, exist_ok=True)

    inventory: list[dict[str, Any]] = []
    for spec in FIGURES:
        if spec.example_id not in examples:
            raise KeyError(f"Missing example in bundle: {spec.example_id}")
        panel_path, rows = build_panel(
            spec, examples[spec.example_id], args.bundle_dir, args.output_dir
        )
        inventory.extend(rows)
        inventory.append(
            inventory_row(
                figure=spec.key,
                role="composed_panel",
                example_id=spec.example_id,
                path=panel_path,
                root=args.output_dir,
                stage="panel",
                page=None,
                kind="panel",
                label=spec.title,
            )
        )

    write_inventory(inventory, args.output_dir)
    write_presentation_handoff(inventory, args.output_dir)
    print(f"Wrote {len(FIGURES)} figure panel(s) to {args.output_dir}")


def load_demo_data(bundle_dir: Path) -> dict[str, Any]:
    data_js = bundle_dir / "assets" / "demo-data.js"
    text = data_js.read_text(encoding="utf-8")
    match = re.match(r"window\.FOCUSPARSE_DEMO_DATA = (.*);\n?$", text)
    if not match:
        raise ValueError(f"Could not parse {data_js}")
    return json.loads(match.group(1))


def build_panel(
    spec: FigureSpec,
    example: dict[str, Any],
    bundle_dir: Path,
    output_dir: Path,
) -> tuple[Path, list[dict[str, Any]]]:
    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), WHITE)
    draw = ImageDraw.Draw(canvas)
    fonts = FontSet()

    draw.text((MARGIN, 48), spec.title, fill=INK, font=fonts.title)
    draw.text((MARGIN, 112), spec.subtitle, fill=MUTED, font=fonts.subhead)

    tile_path = first_tile_path(example, bundle_dir)
    inventory = []
    if tile_path:
        draw_card(
            canvas,
            tile_path,
            box=(MARGIN, 190, 970, 955),
            heading="Trace page overview",
            caption="Pages selected by the final FocusParse +4 run.",
            fonts=fonts,
            accent=GREEN,
        )
        inventory.append(
            inventory_row(
                figure=spec.key,
                role="trace_overview",
                example_id=spec.example_id,
                path=tile_path,
                root=output_dir,
                stage="route_pages",
                page=None,
                kind="tile",
                label="Trace page overview",
            )
        )

    crop_box_y = 190
    crop_card_h = 286
    crop_gap = 30
    for idx, pick in enumerate(spec.picks):
        crop = find_crop(example, pick)
        if crop is None:
            raise KeyError(f"Missing crop for {spec.example_id}: {pick}")
        crop_path = bundle_dir / crop["src"]
        y0 = crop_box_y + idx * (crop_card_h + crop_gap)
        draw_card(
            canvas,
            crop_path,
            box=(1040, y0, CANVAS_W - MARGIN, y0 + crop_card_h),
            heading=f"{chr(ord('A') + idx)}. {pick.role} (page {pick.page})",
            caption="",
            fonts=fonts,
            accent=BLUE if idx < 2 else AMBER,
            trim_image=True,
            focus_box=pick.focus_box,
        )
        inventory.append(
            inventory_row(
                figure=spec.key,
                role=pick.role,
                example_id=spec.example_id,
                path=crop_path,
                root=output_dir,
                stage=pick.stage,
                page=pick.page,
                kind=pick.kind,
                label=pick.label,
            )
        )

    claim_box = (MARGIN, 1165, CANVAS_W - MARGIN, 1335)
    rounded_rect(draw, claim_box, fill=SURFACE, outline=LINE, width=2, radius=18)
    draw.text(
        (claim_box[0] + 28, claim_box[1] + 22), "Mechanism shown", fill=INK, font=fonts.card_title
    )
    draw_wrapped_text(
        draw,
        spec.claim,
        (claim_box[0] + 28, claim_box[1] + 74),
        max_width=claim_box[2] - claim_box[0] - 56,
        fill=MUTED,
        font=fonts.body,
        line_spacing=8,
    )

    draw_process_strip(draw, spec.process, y=1410, fonts=fonts)
    draw.text(
        (MARGIN, CANVAS_H - 92),
        f"Source: final FocusParse +4 run, {example['id']}",
        fill=MUTED,
        font=fonts.small,
    )

    output_path = output_dir / spec.filename
    canvas.save(output_path)
    return output_path, inventory


def find_crop(example: dict[str, Any], pick: CropPick) -> dict[str, Any] | None:
    crops = example["stages"][pick.stage]["crops"]
    for crop in crops:
        if (
            crop.get("page") == pick.page
            and crop.get("kind") == pick.kind
            and crop.get("label") == pick.label
            and crop.get("src")
        ):
            return crop
    return None


def first_tile_path(example: dict[str, Any], bundle_dir: Path) -> Path | None:
    tiles = example.get("tiles") or []
    if not tiles:
        return None
    return bundle_dir / tiles[0]["src"]


class FontSet:
    """Load common fonts with a default PIL fallback."""

    def __init__(self) -> None:
        self.title = load_font(52)
        self.subhead = load_font(28)
        self.card_title = load_font(28)
        self.body = load_font(24)
        self.small = load_font(20)
        self.chip = load_font(24)


def load_font(size: int) -> ImageFont.ImageFont:
    for candidate in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        path = Path(candidate)
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def draw_card(
    canvas: Image.Image,
    image_path: Path,
    *,
    box: tuple[int, int, int, int],
    heading: str,
    caption: str,
    fonts: FontSet,
    accent: tuple[int, int, int],
    trim_image: bool = False,
    focus_box: tuple[float, float, float, float] | None = None,
) -> None:
    draw = ImageDraw.Draw(canvas)
    rounded_rect(draw, box, fill=WHITE, outline=LINE, width=2, radius=20)
    draw.rectangle((box[0], box[1], box[0] + 12, box[3]), fill=accent)
    draw.text((box[0] + 32, box[1] + 22), heading, fill=INK, font=fonts.card_title)

    has_caption = bool(caption.strip())
    image_bottom = box[3] - 92 if has_caption else box[3] - 30
    image_box = (box[0] + 30, box[1] + 72, box[2] - 30, image_bottom)
    with Image.open(image_path) as img:
        source = img.convert("RGB")
        if focus_box is not None:
            source = crop_fraction(source, focus_box)
        if trim_image:
            source = trim_whitespace(source)
        fitted = ImageOps.contain(source, box_size(image_box), Image.Resampling.LANCZOS)
    paste_x = image_box[0] + (box_width(image_box) - fitted.width) // 2
    paste_y = image_box[1] + (box_height(image_box) - fitted.height) // 2
    canvas.paste(fitted, (paste_x, paste_y))

    if has_caption:
        caption_text = one_line(caption, 170)
        draw.text((box[0] + 32, box[3] - 56), caption_text, fill=MUTED, font=fonts.small)


def crop_fraction(img: Image.Image, box: tuple[float, float, float, float]) -> Image.Image:
    left = max(0, min(img.width, int(box[0] * img.width)))
    top = max(0, min(img.height, int(box[1] * img.height)))
    right = max(0, min(img.width, int(box[2] * img.width)))
    bottom = max(0, min(img.height, int(box[3] * img.height)))
    if right <= left or bottom <= top:
        return img
    return img.crop((left, top, right, bottom))


def trim_whitespace(img: Image.Image, *, threshold: int = 246, pad: int = 18) -> Image.Image:
    """Trim near-white margins while preserving a little breathing room."""

    gray = img.convert("L")
    mask = gray.point(lambda pixel: 255 if pixel < threshold else 0)
    bbox = mask.getbbox()
    if bbox is None:
        return img
    left = max(0, bbox[0] - pad)
    top = max(0, bbox[1] - pad)
    right = min(img.width, bbox[2] + pad)
    bottom = min(img.height, bbox[3] + pad)
    if right <= left or bottom <= top:
        return img
    return img.crop((left, top, right, bottom))


def draw_process_strip(
    draw: ImageDraw.ImageDraw, stages: tuple[str, ...], *, y: int, fonts: FontSet
) -> None:
    x = MARGIN
    draw.text((x, y - 50), "Evidence construction path", fill=INK, font=fonts.card_title)
    for idx, stage in enumerate(stages):
        label = stage
        text_box = draw.textbbox((0, 0), label, font=fonts.chip)
        w = text_box[2] - text_box[0] + 46
        box = (x, y, x + w, y + 58)
        rounded_rect(draw, box, fill=SURFACE, outline=LINE, width=2, radius=16)
        draw.text((x + 23, y + 16), label, fill=INK, font=fonts.chip)
        x += w + 42
        if idx < len(stages) - 1:
            draw.line((x - 26, y + 29, x - 5, y + 29), fill=MUTED, width=3)
            draw.polygon([(x - 5, y + 29), (x - 15, y + 22), (x - 15, y + 36)], fill=MUTED)


def draw_wrapped_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    *,
    max_width: int,
    fill: tuple[int, int, int],
    font: ImageFont.ImageFont,
    line_spacing: int,
) -> None:
    words = text.split()
    lines: list[str] = []
    line: list[str] = []
    for word in words:
        trial = " ".join([*line, word])
        if draw.textlength(trial, font=font) <= max_width:
            line.append(word)
        else:
            if line:
                lines.append(" ".join(line))
            line = [word]
    if line:
        lines.append(" ".join(line))
    x, y = xy
    for line_text in lines:
        draw.text((x, y), line_text, fill=fill, font=font)
        y += font_size(font) + line_spacing


def rounded_rect(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    fill: tuple[int, int, int],
    outline: tuple[int, int, int],
    width: int,
    radius: int,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def inventory_row(
    *,
    figure: str,
    role: str,
    example_id: str,
    path: Path,
    root: Path,
    stage: str,
    page: int | None,
    kind: str,
    label: str,
) -> dict[str, Any]:
    with Image.open(path) as img:
        width, height = img.size
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = path.as_posix()
    return {
        "figure": figure,
        "role": role,
        "example_id": example_id,
        "stage": stage,
        "page": "" if page is None else page,
        "kind": kind,
        "label": label,
        "width": width,
        "height": height,
        "relative_path": relative,
        "absolute_path": path.resolve().as_posix(),
    }


def write_inventory(rows: list[dict[str, Any]], output_dir: Path) -> None:
    path = output_dir / "asset-inventory.csv"
    fieldnames = [
        "figure",
        "role",
        "example_id",
        "stage",
        "page",
        "kind",
        "label",
        "width",
        "height",
        "relative_path",
        "absolute_path",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_presentation_handoff(rows: list[dict[str, Any]], output_dir: Path) -> None:
    by_figure: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_figure.setdefault(row["figure"], []).append(row)

    lines = [
        "# FocusParse Paper Qualitative Figure Panels",
        "",
        "Generated from the final May 24 headline FocusParse +4 run.",
        "",
    ]
    for spec in FIGURES:
        lines.extend([f"## {spec.title}", ""])
        panel = next(row for row in by_figure.get(spec.key, []) if row["role"] == "composed_panel")
        lines.extend(
            [
                f"- Example: `{spec.example_id}`",
                f"- Panel PNG: `{panel['absolute_path']}`",
                f"- Claim: {textwrap.fill(spec.claim, width=88)}",
                "",
                "| Role | Page | Asset |",
                "| --- | ---: | --- |",
            ]
        )
        for row in by_figure.get(spec.key, []):
            if row["role"] == "composed_panel":
                continue
            lines.append(f"| {row['role']} | {row['page']} | `{row['absolute_path']}` |")
        lines.append("")

    lines.extend(
        [
            "## Inventory",
            "",
            f"- CSV: `{(output_dir / 'asset-inventory.csv').resolve().as_posix()}`",
            "",
        ]
    )
    (output_dir / "presentation-visuals.md").write_text("\n".join(lines), encoding="utf-8")


def box_width(box: tuple[int, int, int, int]) -> int:
    return box[2] - box[0]


def box_height(box: tuple[int, int, int, int]) -> int:
    return box[3] - box[1]


def box_size(box: tuple[int, int, int, int]) -> tuple[int, int]:
    return (box_width(box), box_height(box))


def font_size(font: ImageFont.ImageFont) -> int:
    bbox = font.getbbox("Ag")
    return bbox[3] - bbox[1]


def one_line(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text)).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


if __name__ == "__main__":
    main()
