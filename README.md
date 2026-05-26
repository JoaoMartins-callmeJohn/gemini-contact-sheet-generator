# Nano Banana Contact Sheet Generator

Generates a photorealistic contact sheet of keyframes using **Nano Banana Pro** (NBP), then slices the grid into individual frame PNGs ready for an image-to-video step (e.g. Kling).

---

## How it works

### 1. You provide two inputs

| Input | What it is |
|---|---|
| **Reference image folder** | One or more photos/renders that establish the visual language — materials, palette, lighting mood, character style. Think of it as a mood board. |
| **Context sheet (`.md`)** | A markdown file with a global style block and one `##` section per shot. |

### 2. Everything goes to the API in a single call

The script builds **one prompt** from your markdown and sends it together with all your reference images in a single `generate_content` request. This is intentional — it mirrors the contact sheet prompting technique where NBP reasons about all frames simultaneously, which is what produces consistent materials, lighting, and spatial language across every frame.

**What that single request contains:**

```
[prompt text]
  └── GLOBAL STYLE     ← the paragraph before the first ## in your .md
  └── SHOT LIST        ← every ## section, numbered and concatenated
  └── OUTPUT FORMAT    ← instructions to produce a cols×rows grid image

[reference image 1]
[reference image 2]
...
```

No streaming, no chunking — one request, one response.

### 3. NBP returns one image: the contact sheet

The response is a single image containing all frames arranged in a grid (e.g. 3 columns × 3 rows for 8 shots). The frames are spatially and stylistically consistent because the model generated them all in one reasoning pass.

### 4. The grid is sliced into individual frames

The script divides the contact sheet by the number of columns and rows, crops out each cell, and saves them as numbered PNGs.

**Output:**

```
output/
  contact_sheet.png          ← full grid as returned by NBP
  frame_001_Entry_Hall.png   ← shot 1 cropped out
  frame_002_Living_Room.png  ← shot 2 cropped out
  ...
```

---

## Context sheet format

```md
[Global style block — no ## header]
Describe render quality, lens, color grade, lighting, materials, and anything
that must stay consistent across every frame.

## Shot 1 — Title
Describe framing, camera angle, subject, depth of field, and mood for this frame.

## Shot 2 — Title
...
```

- The **first paragraph** (before any `##`) is the global style lock — it is prepended to every frame description in the prompt.
- Each `##` section is one cell in the contact sheet grid.
- The number of `##` sections determines the grid size (together with `--grid-cols`).

---

## Running it

```powershell
python generate_video.py
```

The app is interactive — it will ask for each input:

```
==================================================
  Nano Banana Pro — Contact Sheet Generator
==================================================

Reference images folder: D:\my refs
Context sheet (.md / .txt): contact_sheet_interior.md
  API key found in environment (GOOGLE_API_KEY / GEMINI_API_KEY).
Grid columns [3]:
Output folder [output]:
```

| Prompt | Default | Notes |
|---|---|---|
| Reference images folder | — | Must exist; accepts `.png .jpg .jpeg .webp .bmp .tif .tiff` |
| Context sheet | — | Must be an existing `.md` or `.txt` file |
| Google API key | `GOOGLE_API_KEY` or `GEMINI_API_KEY` env var | Hidden input if typed manually |
| Grid columns | `3` | Controls the grid layout; rows are calculated automatically |
| Output folder | `output` | Created if it does not exist |

---

## Reference images — what they do

All reference images are sent together in the same API request as the prompt. They are **not** matched one-to-one with individual shots. NBP uses them collectively as a visual brief — extracting materials, palette, spatial style, and character details — and applies that understanding across every frame.

If you want a specific image to influence a specific shot, mention it in that shot's description:

```md
## Shot 3 — Material Close-Up
Match the marble texture and veining visible in the reference image. Extreme
close-up on the coffee table surface...
```

---

## Requirements

```
google-genai>=0.3.0
Pillow>=10.0.0
imageio>=2.34.0
imageio-ffmpeg>=0.5.0
numpy>=1.26.0
```

Install:

```powershell
pip install -r requirements.txt
```

API key: [Google AI Studio](https://aistudio.google.com/app/apikey)

---

## Next step: Image-to-Video

The extracted frame PNGs are ready to pass into an I2V model. The recommended option is **Kling 2.6** (via API or web UI). Keep the motion prompt minimal — e.g.:

> "The camera very slowly and smoothly pushes in. The scene barely moves. Physically accurate light."

Short clips (2–3 s) with an ease curve applied hide any hallucinations and produce clean transitions when stitched.
