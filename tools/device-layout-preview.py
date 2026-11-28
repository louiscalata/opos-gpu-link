#!/usr/bin/env python3
"""Make clearly labelled, offline mock previews of the two-device layout.

These are drawings, not Android or Tk screenshots. The Android column threshold
is read from DeviceLayoutPolicy.java so the mock follows the host-tested rule.
No app, window, server, or device is started.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from html import escape
from pathlib import Path
import re
import shutil
import struct
import subprocess
import xml.etree.ElementTree as ET
import zlib


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "android/app/src/main/java/os/opos/launcher/DeviceLayoutPolicy.java"
HEAT_METER = ROOT / "android/app/src/main/java/os/opos/launcher/HeatMeter.java"
MODELS_XML = ROOT / "android/app/src/main/res/layout/models.xml"
FONTS = ROOT / "android/app/src/main/res/font"

BLACK = "#000000"
WHITE = "#FFFFFF"
GRAY = "#BFBFBF"
STROKE = "#5C5C5C"
GREEN = "#3DDC84"  # UiPalette.OK_DARK; only a working link or live answer uses it.


def column_threshold() -> int:
    source = POLICY.read_text(encoding="utf-8")
    match = re.search(r"\bTWO_COLUMN_MIN_WIDTH_DP\s*=\s*(\d+)\s*;", source)
    if not match:
        raise RuntimeError("DeviceLayoutPolicy.TWO_COLUMN_MIN_WIDTH_DP is missing")
    return int(match.group(1))


def column_count(width_dp: int, *, cover: bool, lane_count: int) -> int:
    # Match DeviceLayoutPolicy.columns, including its one-lane case.
    return 2 if not cover and width_dp >= column_threshold() and lane_count > 1 else 1


def band_weights() -> tuple[float, float, float]:
    """Use the phone, link, and computer weights from the actual Android XML."""
    android = "{http://schemas.android.com/apk/res/android}"
    wanted = ("device_phone", "device_link", "device_computer")
    weights = {}
    for item in ET.parse(MODELS_XML).getroot().iter():
        item_id = item.get(android + "id", "")
        if item_id.startswith("@+id/"):
            name = item_id[5:]
            if name in wanted:
                weights[name] = float(item.get(android + "layout_weight"))
    if set(weights) != set(wanted):
        raise RuntimeError("Android device band weights are incomplete")
    return tuple(weights[name] for name in wanted)


def place_demo_lanes() -> dict[str, str]:
    """Mirror DeviceLayoutPolicy.column for the four source-named mock lanes."""
    placed = {}
    for name, side in (("Nemotron 3.5 Bolt", "computer"),
                       ("Qwen3.5-2B", "phone"),
                       ("Granite 4.1 3B", "phone"),
                       ("LFM2", "phone")):
        placed[name] = "left" if side == "phone" else "right"
    return placed


def cool_heat_label(*, compact: bool) -> str:
    """Read the cool word and both label prefixes from Android's HeatMeter."""
    source = HEAT_METER.read_text(encoding="utf-8")
    cool = re.search(r'case 0:\s*case 1:\s*return "([^"]+)";', source)
    labels = re.search(
        r'return compact \? "([^"]+)" \+ word\(status\)\s*'
        r':\s*"([^"]+)" \+ word\(status\);', source)
    if not cool or not labels:
        raise RuntimeError("HeatMeter cool labels are missing")
    return (labels.group(1) if compact else labels.group(2)) + cool.group(1)


def heat_row(scene: "Scene", y: float, *, margin: float, scale: float,
             compact: bool = False) -> float:
    """Draw the cool phone reading on its own row, aligned like Android's heat view."""
    size = (14 if compact else 16) * scale
    scene.text(scene.width - margin, y, cool_heat_label(compact=compact),
               size=size, color=WHITE, face="small", anchor="end")
    return y + size


def wrap_words(text: str, max_width: float, size: float) -> list[str]:
    """Conservative fixed measure for the vector mock; the real views wrap text."""
    max_chars = max(12, int(max_width / (size * 0.54)))
    lines: list[str] = []
    line = ""
    for word in text.split():
        if line and len(line) + len(word) + 1 > max_chars:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        lines.append(line)
    return lines


@dataclass
class Operation:
    kind: str
    args: tuple


class Scene:
    def __init__(self, width: int, height: int, background: str = BLACK):
        self.width, self.height = width, height
        self.background = background
        self.operations: list[Operation] = []

    def rect(self, x, y, width, height, *, fill=BLACK, stroke=None, radius=0):
        self.operations.append(Operation("rect", (x, y, width, height, fill, stroke, radius)))

    def line(self, x1, y1, x2, y2, *, color=STROKE, weight=1):
        self.operations.append(Operation("line", (x1, y1, x2, y2, color, weight)))

    def text(self, x, y, value, *, size, color=WHITE, face="body", anchor="start"):
        self.operations.append(Operation("text", (x, y, value, size, color, face, anchor)))

    def text_block(self, x, y, value, *, width, size, color=WHITE,
                   face="body", leading=1.35):
        for line in wrap_words(value, width, size):
            self.text(x, y, line, size=size, color=color, face=face)
            y += size * leading
        return y

    def svg(self) -> str:
        chunks = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" '
            f'height="{self.height}" viewBox="0 0 {self.width} {self.height}">',
            f'<rect width="{self.width}" height="{self.height}" fill="{self.background}"/>',
        ]
        for op in self.operations:
            a = op.args
            if op.kind == "rect":
                x, y, w, h, fill, stroke, radius = a
                s = f' stroke="{stroke}" stroke-width="1"' if stroke else ""
                chunks.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" '
                              f'height="{h:.1f}" rx="{radius:.1f}" fill="{fill}"{s}/>')
            elif op.kind == "line":
                x1, y1, x2, y2, color, weight = a
                chunks.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" '
                              f'y2="{y2:.1f}" stroke="{color}" stroke-width="{weight:.1f}"/>')
            else:
                x, y, value, size, color, face, anchor = a
                family = "serif" if face in {"head", "body"} else "sans-serif"
                weight = "600" if face == "head" else "500" if face == "small" else "400"
                chunks.append(f'<text x="{x:.1f}" y="{y + size:.1f}" '
                              f'font-family="{family}" font-size="{size:.1f}" '
                              f'font-weight="{weight}" fill="{color}" '
                              f'text-anchor="{anchor}">{escape(value)}</text>')
        chunks.append("</svg>")
        return "\n".join(chunks)


ANSWER = ("Each model's reply appears in its own card as the words arrive. "
          "The card grows with the full answer, so there is room to read and compare. ")
SHORT_ANSWER = "This answer appears here as its words arrive. The card grows with the reply."


def device_band(scene: Scene, y: float, *, margin: float, scale: float,
                compact: bool = False) -> float:
    """Phone panel stays left; connected computer stays right at every size."""
    phone_weight, link_weight, computer_weight = band_weights()
    unit = (scene.width - 2 * margin) / sum((phone_weight, link_weight, computer_weight))
    width = phone_weight * unit
    gap = link_weight * unit
    right_width = computer_weight * unit
    height = (44 if compact else 64) * scale
    left_x = margin
    right_x = margin + width + gap
    scene.rect(left_x, y, width, height, stroke=STROKE)
    scene.rect(right_x, y, right_width, height, stroke=STROKE)
    small = (10 if compact else 11) * scale
    head = (17 if compact else 21) * scale
    if not compact:
        scene.text(left_x + 8 * scale, y + 6 * scale, "PHONE", size=small,
                   color=GRAY, face="small")
        scene.text(right_x + 8 * scale, y + 6 * scale, "COMPUTER", size=small,
                   color=GRAY, face="small")
    name_y = y + (24 if not compact else 10) * scale
    scene.text(left_x + 8 * scale, name_y, "Phone", size=head, face="head")
    # The actual UI resolves the connected label. MacBook is source-derived from
    # computer_noun(); the mock makes no claim about the live machine name.
    scene.text(right_x + 8 * scale, name_y, "MacBook", size=head, face="head")
    center_y = y + height / 2
    link_center = left_x + width + gap / 2
    scene.text(link_center, center_y - 12 * scale, "USB-C",
               size=small, color=GREEN, face="small", anchor="middle")
    scene.text(link_center, center_y + 2 * scale, "Connected",
               size=small, color=GREEN, face="small", anchor="middle")
    return y + height


def article(scene: Scene, x: float, y: float, width: float, *, scale: float,
            name: str, maker: str, where: str, paragraphs: int,
            baseline: bool = False, live: bool = False,
            cover: bool = False, body_text: str | None = None) -> float:
    pad = 8 * scale
    head = (17 if cover else 21) * scale
    small = (10 if cover else 11) * scale
    body = (14 if cover else 17) * scale
    paragraph = body_text if body_text is not None else ANSWER * paragraphs
    lines = wrap_words(paragraph, width - 2 * pad, body)
    body_top = y + (55 if cover else 82) * scale
    bottom = body_top + len(lines) * body * 1.35 + (8 if cover else 17) * scale
    height = bottom - y
    scene.rect(x, y, width, height, stroke=STROKE)
    label = (where + " · COMPARISON BASELINE") if baseline else where
    scene.text(x + pad, y + 8 * scale, label,
               size=small, color=GRAY, face="small")
    scene.text(x + pad, y + (17 if cover else 26) * scale,
               name, size=head, face="head")
    scene.text(x + pad, y + (37 if cover else 51) * scale,
               maker, size=small, color=GRAY, face="small")
    if live:
        scene.text(x + width - pad, y + 8 * scale, "LIVE", size=small,
                   color=GREEN, face="small", anchor="end")
    rule_y = y + (50 if cover else 76) * scale
    scene.line(x + pad, rule_y, x + width - pad, rule_y)
    for line in lines:
        scene.text(x + pad, body_top, line, size=body, face="body")
        body_top += body * 1.35
    return y + height


def scroll_cue(scene: Scene, scale: float, margin: float) -> None:
    """A mock-only viewport cue when more answer cards continue below."""
    top = scene.height - 23 * scale
    scene.rect(0, top, scene.width, 23 * scale, fill=BLACK)
    scene.line(margin, top, scene.width - margin, top, color=STROKE)
    scene.text(scene.width / 2, top + 4 * scale, "Scroll for more answers",
               size=11 * scale, color=GRAY, face="small", anchor="middle")


def inner_scene(width: int, height: int, *, landscape: bool) -> Scene:
    scene = Scene(width, height)
    width_dp = 880 if landscape else 360
    scale = width / width_dp
    margin = 12 * scale
    small = 11 * scale
    head = 21 * scale
    scene.text(margin, 4 * scale, "MOCK PREVIEW · INNER LANDSCAPE" if landscape
               else "MOCK PREVIEW · INNER PORTRAIT", size=small, color=GRAY, face="small")
    scene.text(margin, 20 * scale, "GPU LINK",
               size=(28 if landscape else 34) * scale, face="head")
    heat_bottom = heat_row(scene, (52 if landscape else 65) * scale,
                           margin=margin, scale=scale)
    band_y = heat_bottom + 8 * scale
    bottom_band = device_band(scene, band_y, margin=margin, scale=scale)
    question_y = bottom_band + 10 * scale
    scene.text(margin, question_y, "YOUR QUESTION", size=small, color=GRAY,
               face="small")
    scene.text(margin, question_y + 18 * scale, "What can this setup do?",
               size=head, face="head")
    top = question_y + 52 * scale
    count = column_count(width_dp, cover=False, lane_count=4)
    gap = 6 * scale
    if count == 2:
        col_width = (width - margin * 2 - gap) / 2
        left_x, right_x = margin, margin + col_width + gap
        next_y = {"left": top, "right": top}
        x_for = {"left": left_x, "right": right_x}
        placements = place_demo_lanes()
        for name, maker, where, baseline, live, sample in (
            ("Nemotron 3.5 Bolt", "NVIDIA", "MACBOOK GPU", False, True, SHORT_ANSWER),
            ("Qwen3.5-2B", "Qwen (Alibaba)", "PHONE", False, True, SHORT_ANSWER),
            ("Granite 4.1 3B", "IBM", "PHONE", False, False, ANSWER),
            ("LFM2", "Liquid AI", "PHONE", True, False, ANSWER),
        ):
            column = placements[name]
            next_y[column] = article(scene, x_for[column], next_y[column], col_width,
                                     scale=scale, name=name, maker=maker, where=where,
                                     paragraphs=1, baseline=baseline, live=live,
                                     body_text=sample) + gap
    else:
        card_width = width - 2 * margin
        top = article(scene, margin, top, card_width, scale=scale,
                name="Nemotron 3.5 Bolt", maker="NVIDIA", where="MACBOOK GPU",
                paragraphs=1, live=True) + gap
        top = article(scene, margin, top, card_width, scale=scale,
                      name="Qwen3.5-2B", maker="Qwen (Alibaba)", where="PHONE",
                      paragraphs=1, live=True) + gap
        top = article(scene, margin, top, card_width, scale=scale,
                      name="Granite 4.1 3B", maker="IBM", where="PHONE",
                      paragraphs=1) + gap
        article(scene, margin, top, card_width, scale=scale,
                name="LFM2", maker="Liquid AI", where="PHONE",
                paragraphs=1, baseline=True)
    scroll_cue(scene, scale, margin)
    return scene


def cover_scene() -> Scene:
    width, height = 720, 748
    scene = Scene(width, height)
    margin = 24
    scene.text(margin, 5, "MOCK PREVIEW · COVER", size=22, color=GRAY, face="small")
    scene.text(margin, 27, "GPU LINK", size=48, face="head")
    heat_bottom = heat_row(scene, 80, margin=margin, scale=2, compact=True)
    # CoverScreenPolicy: a 52 dp composer row above the results at 2 px per dp.
    prompt_x, composer_y, composer_h = margin, heat_bottom + 10, 104
    button_w, button_gap = 168, 12  # 84 dp action and 6 dp margin.
    prompt_w = width - 2 * margin - button_w - button_gap
    scene.rect(prompt_x, composer_y, prompt_w, composer_h, stroke=STROKE)
    scene.text(prompt_x + 20, composer_y + 33, "Ask the models…",
               size=28, color=GRAY, face="body")
    button_x = prompt_x + prompt_w + button_gap
    scene.rect(button_x, composer_y, button_w, composer_h, fill=WHITE)
    scene.text(button_x + button_w / 2, composer_y + 34, "Send", size=34,
               color=BLACK, face="head", anchor="middle")

    band_bottom = device_band(scene, composer_y + composer_h + 10,
                              margin=margin, scale=2, compact=True)
    # One compact answer fits between the band and the pinned bottom dock.
    article(scene, margin, band_bottom + 16, width - 2 * margin, scale=2,
            name="Nemotron 3.5 Bolt", maker="NVIDIA", where="MACBOOK GPU",
            paragraphs=1, body_text="Words arrive here.", live=True, cover=True)

    # NotesSheet: 48 dp notes touch row and a 72 dp cover summary cap.
    notes_top, summary_top = 508, 604
    scene.line(margin, notes_top, width - margin, notes_top, color=STROKE)
    scene.text(width / 2, notes_top + 32, "NOTES", size=20, color=WHITE,
               face="small", anchor="middle")
    scene.rect(margin, summary_top, width - 2 * margin, height - summary_top,
               stroke=STROKE)
    scene.text(margin + 16, summary_top + 12, "SUMMARY", size=20,
               color=WHITE, face="small")
    scene.text_block(margin + 16, summary_top + 43,
                     "Ask the models to compare their answers.",
                     width=width - 2 * margin - 32, size=28, face="body")
    return scene


def tk_scene() -> Scene:
    width, height = 1100, 720
    scene = Scene(width, height, background=WHITE)
    margin = 18
    scene.text(margin, 10, "MOCK PREVIEW · MAC COMPANION", size=11,
               color=STROKE, face="small")
    scene.text(margin, 35, "OPOS GPU Link", size=21, color=BLACK, face="head")
    band_y, band_height = 77, 72
    band_gap = 106
    panel_width = (width - 2 * margin - band_gap) / 2
    right_x = margin + panel_width + band_gap
    for x in (margin, right_x):
        scene.rect(x, band_y, panel_width, band_height,
                   fill=WHITE, stroke=BLACK)
    scene.text(margin + 12, band_y + 24, "Phone", size=21,
               color=BLACK, face="head")
    scene.text(right_x + 12, band_y + 24, "MacBook", size=21,
               color=BLACK, face="head")
    scene.text(width / 2, band_y + 20, "USB-C", size=11,
               color="#008000", face="small", anchor="middle")
    scene.text(width / 2, band_y + 39, "Connected", size=11,
               color="#008000", face="small", anchor="middle")
    status_y, status_height = 163, 484
    scene.rect(margin, status_y, width - 2 * margin, status_height,
               fill=WHITE, stroke=BLACK)
    scene.text(margin + 12, status_y + 10, "STATUS", size=11,
               color=BLACK, face="small")
    scene.text(margin + 12, status_y + 34,
               "Phone connected; waiting for requests", size=17,
               color=BLACK, face="body")
    controls = ("Retry connection", "Remove model copies", "Stop GPU Link")
    button_gap = 8
    button_width = (width - 2 * margin - button_gap * 2) / 3
    for index, label in enumerate(controls):
        x = margin + index * (button_width + button_gap)
        scene.rect(x, 661, button_width, 42, fill=WHITE, stroke=BLACK)
        scene.text(x + button_width / 2, 673, label, size=11, color=BLACK,
                   face="small", anchor="middle")
    return scene


def _pillow_png(scene: Scene, output: Path) -> bool:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False
    image = Image.new("RGB", (scene.width, scene.height), scene.background)
    draw = ImageDraw.Draw(image)
    font_files = {
        "head": FONTS / "source_serif_subhead_semibold.ttf",
        "body": FONTS / "source_serif_text_regular.ttf",
        "small": FONTS / "inter_medium.ttf",
    }
    for op in scene.operations:
        a = op.args
        if op.kind == "rect":
            x, y, w, h, fill, stroke, radius = a
            draw.rounded_rectangle((x, y, x + w, y + h), radius=radius,
                                   fill=fill, outline=stroke, width=1)
        elif op.kind == "line":
            x1, y1, x2, y2, color, weight = a
            draw.line((x1, y1, x2, y2), fill=color, width=max(1, round(weight)))
        else:
            x, y, value, size, color, face, anchor = a
            font = ImageFont.truetype(str(font_files[face]), max(1, round(size)))
            if anchor == "middle":
                x -= draw.textlength(value, font=font) / 2
            elif anchor == "end":
                x -= draw.textlength(value, font=font)
            draw.text((x, y), value, fill=color, font=font)
    image.save(output)
    return True


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    data = kind + payload
    return struct.pack(">I", len(payload)) + data + struct.pack(">I", zlib.crc32(data))


def _stdlib_png(scene: Scene, output: Path) -> None:
    """Last-resort offline PNG: geometry and text blocks, with no font library."""
    width, height = scene.width, scene.height
    pixels = bytearray(bytes.fromhex(scene.background.lstrip("#")) * width * height)

    def color(hex_rgb):
        return bytes.fromhex(hex_rgb.lstrip("#"))

    def fill_rect(x0, y0, x1, y1, rgb):
        x0, x1 = max(0, int(x0)), min(width, int(x1))
        y0, y1 = max(0, int(y0)), min(height, int(y1))
        c = color(rgb)
        for yy in range(y0, y1):
            start = (yy * width + x0) * 3
            pixels[start:start + (x1 - x0) * 3] = c * (x1 - x0)

    def line(x0, y0, x1, y1, rgb, weight):
        steps = max(1, round(max(abs(x1 - x0), abs(y1 - y0))))
        for i in range(steps + 1):
            t = i / steps
            x = x0 + (x1 - x0) * t
            y = y0 + (y1 - y0) * t
            fill_rect(x, y, x + max(1, weight), y + max(1, weight), rgb)

    for op in scene.operations:
        a = op.args
        if op.kind == "rect":
            x, y, w, h, fill, stroke, _ = a
            fill_rect(x, y, x + w, y + h, fill)
            if stroke:
                line(x, y, x + w, y, stroke, 1)
                line(x, y + h, x + w, y + h, stroke, 1)
                line(x, y, x, y + h, stroke, 1)
                line(x + w, y, x + w, y + h, stroke, 1)
        elif op.kind == "line":
            line(*a)
        else:
            x, y, value, size, rgb, _, anchor = a
            # With no installed renderer, use one small bar per word.
            # The PNG still preserves the text measure and spacing.
            words = value.split()
            widths = [max(5, len(word) * size * 0.40) for word in words]
            total = sum(widths) + max(0, len(words) - 1) * size * 0.35
            if anchor == "middle":
                x -= total / 2
            elif anchor == "end":
                x -= total
            for word_width in widths:
                fill_rect(x, y + size * 0.47, x + word_width,
                          y + size * 0.59, rgb)
                x += word_width + size * 0.35

    raw = b"".join(b"\x00" + pixels[y * width * 3:(y + 1) * width * 3]
                   for y in range(height))
    header = b"\x89PNG\r\n\x1a\n"
    header += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    output.write_bytes(header + _png_chunk(b"IDAT", zlib.compress(raw, 6))
                       + _png_chunk(b"IEND", b""))


def save(scene: Scene, output: Path) -> str:
    output.parent.mkdir(parents=True, exist_ok=True)
    if _pillow_png(scene, output):
        return "Pillow"
    renderer = shutil.which("rsvg-convert")
    if renderer:
        subprocess.run([renderer, "-o", str(output)], input=scene.svg().encode("utf-8"),
                       check=True)
        return "librsvg"
    _stdlib_png(scene, output)
    return "standard library"


def generate(output_dir: Path) -> list[tuple[Path, str]]:
    scenes = {
        "mock-inner-portrait.png": inner_scene(1080, 2640, landscape=False),
        "mock-inner-landscape.png": inner_scene(2640, 1080, landscape=True),
        "mock-cover.png": cover_scene(),
        "mock-mac-companion.png": tk_scene(),
    }
    return [(output_dir / name, save(scene, output_dir / name))
            for name, scene in scenes.items()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    for path, renderer in generate(args.output_dir):
        print(f"{path}: mock PNG via {renderer}")


if __name__ == "__main__":
    main()
