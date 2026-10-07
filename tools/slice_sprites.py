#!/usr/bin/env python3
"""Slice Naruto Arena character sheets into transparent frames and previews."""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "assets" / "raw"
OUT_DIR = ROOT / "assets" / "sprites"
MAGENTA = (248, 0, 248)
SHEET_GRAY = (206, 213, 223)
CHARACTERS = ("naruto", "sasuke")


def components(mask: Image.Image, *, min_area: int = 1) -> list[tuple[int, int, int, int]]:
    """Return 4-connected component bounds from a one-bit image (right/bottom exclusive)."""
    pixels = mask.load()
    width, height = mask.size
    seen = bytearray(width * height)
    result = []
    for y in range(height):
        for x in range(width):
            pos = y * width + x
            if seen[pos] or not pixels[x, y]:
                continue
            seen[pos] = 1
            queue = deque([(x, y)])
            left = right = x
            top = bottom = y
            area = 0
            while queue:
                px, py = queue.popleft()
                area += 1
                left, right = min(left, px), max(right, px)
                top, bottom = min(top, py), max(bottom, py)
                for nx, ny in ((px - 1, py), (px + 1, py), (px, py - 1), (px, py + 1)):
                    if 0 <= nx < width and 0 <= ny < height:
                        npos = ny * width + nx
                        if not seen[npos] and pixels[nx, ny]:
                            seen[npos] = 1
                            queue.append((nx, ny))
            if area >= min_area:
                result.append((left, top, right + 1, bottom + 1))
    return result


def checkerboard(size: tuple[int, int], tile: int = 12) -> Image.Image:
    image = Image.new("RGB", size, (238, 238, 238))
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], tile):
        for x in range(0, size[0], tile):
            if (x // tile + y // tile) % 2:
                draw.rectangle((x, y, x + tile - 1, y + tile - 1), fill=(202, 202, 202))
    return image


def make_preview(row_number: int, frames: list[dict], output: Path) -> None:
    pad, label_h, gap = 8, 22, 6
    cell_w = max(frame["image"].width for frame in frames)
    cell_h = max(frame["image"].height for frame in frames)
    width = pad * 2 + len(frames) * cell_w + (len(frames) - 1) * gap
    height = pad * 2 + label_h + cell_h
    preview = checkerboard((width, height))
    draw = ImageDraw.Draw(preview)
    for index, frame in enumerate(frames, 1):
        x = pad + (index - 1) * (cell_w + gap)
        draw.text((x, pad), f"{index:02d}", fill=(20, 20, 20))
        image = frame["image"]
        preview.paste(image, (x + (cell_w - image.width) // 2, pad + label_h), image)
    preview.save(output)


def make_all_previews(rows: list[list[list[dict]]], out: Path) -> None:
    """Write vertically stacked, 2x nearest-neighbor previews, chunked for readability."""
    scale, pad, label_h, gap, row_label_w = 2, 12, 24, 8, 72
    row_heights = [label_h + max(frame["image"].height for frame in row) * scale + gap for row in rows]
    chunks: list[list[int]] = []
    current: list[int] = []
    current_height = pad * 2
    for row_index, row_height in enumerate(row_heights):
        if current and (len(current) >= 12 or current_height + row_height > 4000):
            chunks.append(current)
            current, current_height = [], pad * 2
        current.append(row_index)
        current_height += row_height
    if current:
        chunks.append(current)

    split = len(chunks) > 1
    for part, row_indices in enumerate(chunks, 1):
        max_frame_w = max(frame["image"].width * scale for i in row_indices for frame in rows[i])
        max_frames = max(len(rows[i]) for i in row_indices)
        cell_w = max_frame_w + gap
        width = pad * 2 + row_label_w + max_frames * cell_w
        height = pad * 2 + sum(row_heights[i] for i in row_indices)
        canvas = checkerboard((width, height))
        draw = ImageDraw.Draw(canvas)
        y = pad
        for row_index in row_indices:
            row = rows[row_index]
            draw.text((pad, y + 4), f"row_{row_index:02d}", fill=(20, 20, 20))
            content_y = y + label_h
            for frame_index, frame in enumerate(row):
                x = pad + row_label_w + frame_index * cell_w
                draw.text((x, y + 4), f"{frame_index + 1:02d}", fill=(20, 20, 20))
                image = frame["image"].resize(
                    (frame["image"].width * scale, frame["image"].height * scale),
                    Image.Resampling.NEAREST,
                )
                canvas.paste(image, (x, content_y), image)
            y += row_heights[row_index]
        filename = f"preview_all_{part}.png" if split else "preview_all.png"
        canvas.save(out / filename)


def process(character: str) -> tuple[int, int]:
    source = Image.open(RAW_DIR / f"{character}.png").convert("RGB")
    width, height = source.size
    magenta_mask = Image.new("1", source.size)
    src_pixels, mask_pixels = source.load(), magenta_mask.load()
    for y in range(height):
        for x in range(width):
            mask_pixels[x, y] = src_pixels[x, y] == MAGENTA

    boxes = [box for box in components(magenta_mask, min_area=100)
             if box[2] - box[0] >= 12 and box[3] - box[1] >= 12]
    boxes.sort(key=lambda b: (b[1], b[0]))

    out = OUT_DIR / character
    out.mkdir(parents=True, exist_ok=True)
    rows: list[list[tuple[int, int, int, int]]] = []
    # Group frames by their vertical overlap; lines may have a small y offset.
    for box in boxes:
        for row in rows:
            top = min(b[1] for b in row)
            bottom = max(b[3] for b in row)
            overlap = min(bottom, box[3]) - max(top, box[1])
            if overlap > 0 and overlap >= min(box[3] - box[1], bottom - top) * 0.35:
                row.append(box)
                break
        else:
            rows.append([box])
    rows.sort(key=lambda row: min(b[1] for b in row))
    for row in rows:
        row.sort(key=lambda b: b[0])

    metadata = {"character": character, "source": f"assets/raw/{character}.png", "rows": []}
    frame_boxes = []
    all_preview_rows = []
    for row_index, row in enumerate(rows):
        row_dir = out / f"row_{row_index:02d}"
        row_dir.mkdir(parents=True, exist_ok=True)
        preview_frames = []
        row_metadata = []
        for frame_index, box in enumerate(row, 1):
            frame_boxes.append(box)
            crop = source.crop(box).convert("RGBA")
            cp = crop.load()
            for y in range(crop.height):
                for x in range(crop.width):
                    if cp[x, y][:3] in (MAGENTA, SHEET_GRAY):
                        cp[x, y] = (0, 0, 0, 0)
            alpha = crop.getchannel("A")
            content_box = alpha.getbbox()
            if content_box:
                trimmed = crop.crop(content_box)
            else:
                trimmed = crop
                content_box = (0, 0, crop.width, crop.height)
            # Anchor is the bottom-center of the trimmed image; preserve its source-frame location.
            anchor = [trimmed.width // 2, trimmed.height]
            rel_path = f"row_{row_index:02d}/frame_{frame_index:02d}.png"
            trimmed.save(out / rel_path)
            item = {"path": f"assets/sprites/{character}/{rel_path}",
                    "size": [trimmed.width, trimmed.height],
                    "anchor": anchor,
                    "source_bbox": list(box),
                    "trim_offset": [box[0] + content_box[0], box[1] + content_box[1]]}
            row_metadata.append(item)
            preview_frames.append({"image": trimmed})
        make_preview(row_index, preview_frames, out / f"preview_row_{row_index:02d}.png")
        metadata["rows"].append({"row": row_index, "frames": row_metadata})
        all_preview_rows.append(preview_frames)
    make_all_previews(all_preview_rows, out)
    (out / "frames.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Effects are the non-gray artwork in the upper-right region, excluding every frame rectangle.
    effects_dir = out / "effects"
    effects_dir.mkdir(parents=True, exist_ok=True)
    effect_mask = Image.new("1", source.size)
    ep = effect_mask.load()
    x_min, y_max = int(width * 0.64), int(height * 0.12)
    blocked = bytearray(width * y_max)
    for left, top, right, bottom in frame_boxes:
        if top >= y_max or left >= width:
            continue
        for yy in range(max(0, top), min(y_max, bottom)):
            blocked[yy * width + max(0, left):yy * width + min(width, right)] = b"\x01" * (min(width, right) - max(0, left))
    for y in range(y_max):
        for x in range(x_min, width):
            color = src_pixels[x, y]
            if color != SHEET_GRAY and not blocked[y * width + x]:
                ep[x, y] = 1
    effect_boxes = components(effect_mask, min_area=20)
    effect_index = 0
    for box in sorted(effect_boxes, key=lambda b: (b[1], b[0])):
        # Remove exact sheet gray if enclosed and trim to actual non-background pixels.
        crop = source.crop(box).convert("RGBA")
        px = crop.load()
        for y in range(crop.height):
            for x in range(crop.width):
                if px[x, y][:3] == SHEET_GRAY:
                    px[x, y] = (0, 0, 0, 0)
        content = crop.getchannel("A").getbbox()
        if not content:
            continue
        effect_index += 1
        crop.crop(content).save(effects_dir / f"effect_{effect_index:02d}.png")

    return len(rows), sum(len(row) for row in rows)


def main() -> None:
    for character in CHARACTERS:
        row_count, frame_count = process(character)
        print(f"{character}: {row_count} linhas, {frame_count} quadros")


if __name__ == "__main__":
    main()
