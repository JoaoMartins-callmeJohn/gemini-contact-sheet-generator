"""Generate a contact sheet + extract keyframes using Nano Banana Pro.

Workflow
--------
1. Load reference images from a folder.
2. Parse a context sheet (.md / .txt) that describes the shot list and style.
3. Build a single contact-sheet prompt and send it to NBP in one pass — this
   lets the model reason about all keyframes simultaneously, which is what
   produces consistent characters, lighting, and style across frames.
4. Receive the contact sheet image (a grid of N frames) and slice it into
   individual keyframe PNGs saved to --output-dir.

The contact sheet image itself is also saved so you can inspect it or pass it
on to an I2V step (e.g. Kling 2.6) manually.
"""

from __future__ import annotations

import io
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from google import genai
from google.genai import types

NANO_BANANA_PRO = "gemini-3-pro-image-preview"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ShotEntry:
    index: int
    title: str
    description: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_reference_images(folder: Path) -> list[tuple[Path, Image.Image]]:
    if not folder.is_dir():
        raise FileNotFoundError(f"Image folder not found: {folder}")
    paths = sorted(
        p for p in folder.iterdir()
        if p.suffix.lower() in IMAGE_EXTS and p.is_file()
    )
    if not paths:
        raise ValueError(
            f"No images found in {folder} (looked for {sorted(IMAGE_EXTS)})"
        )
    return [(p, Image.open(p).convert("RGB")) for p in paths]


def parse_context_sheet(path: Path) -> tuple[str, list[ShotEntry]]:
    """Return (global_style, shots).

    The leading text before the first ``##`` header is the global style block
    (palette, mood, render quality, lens, etc.).  Each ``##`` section is one
    shot in the contact sheet.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Context sheet not found: {path}")
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        raise ValueError("Context sheet is empty.")

    header_re = re.compile(r"^#{2,3}\s+(.*)$", re.MULTILINE)
    matches = list(header_re.finditer(raw))

    if matches:
        global_style = raw[: matches[0].start()].strip()
        shots: list[ShotEntry] = []
        for i, m in enumerate(matches):
            title = m.group(1).strip()
            body_start = m.end()
            body_end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
            body = raw[body_start:body_end].strip()
            if body:
                shots.append(ShotEntry(index=i, title=title, description=body))
        if shots:
            return global_style, shots

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
    if len(paragraphs) > 1:
        return "", [ShotEntry(i, f"Shot {i + 1}", p) for i, p in enumerate(paragraphs)]
    return "", [ShotEntry(0, "Shot 1", raw)]


def build_contact_sheet_prompt(
    global_style: str,
    shots: list[ShotEntry],
    grid_cols: int,
) -> str:
    """Build the single NBP prompt that generates the full contact sheet."""
    n = len(shots)
    grid_rows = (n + grid_cols - 1) // grid_cols

    shot_list = "\n\n".join(
        f"Frame {s.index + 1} — {s.title}:\n{s.description}"
        for s in shots
    )

    return f"""Analyze every attached reference image and silently inventory all \
critical visual details: subjects, exact materials, colors, textures, lighting \
direction, shadow quality, spatial geometry, and overall mood.

All style, lighting, materials, color grade, and spatial language described \
below must remain 100% consistent across every frame. Do not reinterpret, \
add, or remove anything. Do not output reasoning or text — only the image.

GLOBAL STYLE:
{global_style}

SHOT LIST ({n} frames):
{shot_list}

OUTPUT FORMAT:
A single contact sheet image arranged as a {grid_cols}-column × {grid_rows}-row \
grid containing exactly {n} frames.  All frames must share the same aspect ratio. \
Each frame is a photorealistic, high-detail still — not a sketch or illustration. \
Frames must feel like camera placements within the same coherent scene or space, \
not unrelated shots.  Maintain perfect visual continuity across the entire grid."""


def generate_contact_sheet(
    client: genai.Client,
    model: str,
    prompt: str,
    references: list[Image.Image],
    retries: int = 3,
) -> Image.Image:
    contents: list[object] = [prompt, *references]
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                ),
            )
            for part in response.candidates[0].content.parts:
                if getattr(part, "inline_data", None) and part.inline_data.data:
                    return Image.open(
                        io.BytesIO(part.inline_data.data)
                    ).convert("RGB")
            raise RuntimeError("Model returned no image part.")
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < retries:
                wait = 2 ** attempt
                print(
                    f"  ! attempt {attempt} failed ({e}); retrying in {wait}s",
                    file=sys.stderr,
                )
                time.sleep(wait)
    assert last_err is not None
    raise last_err


def extract_frames(
    contact_sheet: Image.Image,
    n_frames: int,
    grid_cols: int,
) -> list[Image.Image]:
    """Slice the contact sheet grid into individual frame images."""
    grid_rows = (n_frames + grid_cols - 1) // grid_cols
    sheet_w, sheet_h = contact_sheet.size
    cell_w = sheet_w // grid_cols
    cell_h = sheet_h // grid_rows

    frames: list[Image.Image] = []
    for idx in range(n_frames):
        row = idx // grid_cols
        col = idx % grid_cols
        left = col * cell_w
        top = row * cell_h
        right = left + cell_w
        bottom = top + cell_h
        frames.append(contact_sheet.crop((left, top, right, bottom)))
    return frames


# ---------------------------------------------------------------------------
# Console prompts
# ---------------------------------------------------------------------------

def prompt_folder() -> Path:
    while True:
        raw = input("Reference images folder: ").strip().strip('"').strip("'")
        if not raw:
            print("  Please enter a path.")
            continue
        p = Path(raw)
        if not p.is_dir():
            print(f"  Folder not found: {p}")
            continue
        return p


def prompt_context() -> Path:
    while True:
        raw = input("Context sheet (.md / .txt): ").strip().strip('"').strip("'")
        if not raw:
            print("  Please enter a path.")
            continue
        p = Path(raw)
        if not p.is_file():
            print(f"  File not found: {p}")
            continue
        return p


def prompt_api_key() -> str:
    env_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if env_key:
        masked = env_key[:4] + "*" * (len(env_key) - 8) + env_key[-4:]
        print(f"  API key found in environment: {masked}")
        return env_key
    while True:
        key = input("Google API key: ").strip()
        if key:
            masked = key[:4] + "*" * (len(key) - 8) + key[-4:]
            print(f"  Key received: {masked}")
            return key
        print("  API key cannot be empty.")


def prompt_grid_cols() -> int:
    while True:
        raw = input("Grid columns [3]: ").strip()
        if not raw:
            return 3
        if raw.isdigit() and int(raw) >= 1:
            return int(raw)
        print("  Enter a positive integer.")


def prompt_output_dir() -> Path:
    raw = input("Output folder [output]: ").strip().strip('"').strip("'")
    return Path(raw) if raw else Path("output")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 50)
    print("  Nano Banana Pro — Contact Sheet Generator")
    print("=" * 50)
    print()

    folder = prompt_folder()
    context = prompt_context()
    api_key = prompt_api_key()
    grid_cols = prompt_grid_cols()
    output_dir = prompt_output_dir()

    print()
    print(f"Loading reference images from {folder} ...")
    refs = load_reference_images(folder)
    print(f"  {len(refs)} reference image(s) loaded.")

    print(f"Parsing context sheet {context} ...")
    global_style, shots = parse_context_sheet(context)
    print(f"  {len(shots)} shot(s) detected.")

    client = genai.Client(api_key=api_key)
    ref_images = [img for _, img in refs]

    prompt = build_contact_sheet_prompt(global_style, shots, grid_cols)

    print(f"Generating contact sheet ({len(shots)} frames, {grid_cols}-column grid) ...")
    contact_sheet = generate_contact_sheet(client, NANO_BANANA_PRO, prompt, ref_images)

    output_dir.mkdir(parents=True, exist_ok=True)
    sheet_path = output_dir / "contact_sheet.png"
    contact_sheet.save(sheet_path)
    print(f"  Contact sheet saved -> {sheet_path}")

    print("Extracting individual frames ...")
    frames = extract_frames(contact_sheet, len(shots), grid_cols)
    for i, (frame, shot) in enumerate(zip(frames, shots)):
        safe_title = re.sub(r"[^\w\-]", "_", shot.title)
        frame_path = output_dir / f"frame_{i + 1:03d}_{safe_title}.png"
        frame.save(frame_path)
        print(f"  [{i + 1}/{len(shots)}] {shot.title} -> {frame_path}")

    print(f"\nDone. {len(frames)} frame(s) saved to {output_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
