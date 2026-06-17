#!/usr/bin/env python3
"""
Meeting transcription with on-screen content.

Transcribes a meeting video's audio (local Whisper) AND reads what appears on
screen (slides, app demos, shared documents) via Claude vision, then merges both
into one timestamped Markdown timeline. The speech is grouped under the screen
that was visible while it was spoken.

Audio runs locally (no API cost). The visual pass sends one frame per scene
change to Claude (a handful of cents for a typical meeting). Source video is
never moved or modified.

Usage:
    ./venv/bin/python transcribe_meeting.py "path/to/meeting.mp4"
    ./venv/bin/python transcribe_meeting.py "meeting.mp4" --max-seconds 120   # quick test slice
    ./venv/bin/python transcribe_meeting.py "meeting.mp4" --no-vision         # audio only
    ./venv/bin/python transcribe_meeting.py "meeting.mp4" --output "notes.md"

Defaults: Whisper "medium", Spanish, scene threshold 0.3, vision model
claude-sonnet-4-6 (good and cheap for OCR/UI description; pass --vision-model to
override). The Anthropic key is read from `secret anthropic` (macOS Keychain) or
the ANTHROPIC_API_KEY environment variable.
"""

import argparse
import base64
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


# ----------------------------- helpers ---------------------------------------

def run(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def ffprobe_duration(video: Path) -> float:
    r = run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(video),
    ])
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def fmt_ts(seconds: float) -> str:
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def get_anthropic_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key.strip()
    r = run(["secret", "anthropic"])
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    return None


# ----------------------------- audio -----------------------------------------

def transcribe_audio(video: Path, model_size: str, language: str):
    import whisper

    print(f"Loading Whisper model '{model_size}' (first run downloads it)...")
    model = whisper.load_model(model_size)
    print("Transcribing audio (this can take a few minutes)...")
    result = model.transcribe(str(video), language=language, verbose=False)
    segments = [
        {"start": float(s["start"]), "end": float(s["end"]), "text": s["text"].strip()}
        for s in result.get("segments", [])
        if s.get("text", "").strip()
    ]
    print(f"  {len(segments)} speech segments.")
    return segments


# ----------------------------- frames ----------------------------------------

def extract_frames(video: Path, workdir: Path, scene_threshold: float, max_long_edge: int):
    """Extract one frame per scene change (plus an opening frame at t=0).

    Returns a list of {"time": float, "path": Path} sorted by time.
    """
    frames = []
    scale = f"scale='min({max_long_edge},iw)':-2"

    # Opening frame at t=0 as a baseline (scene detection only fires on changes).
    opening = workdir / "frame_0000.jpg"
    run([
        "ffmpeg", "-y", "-i", str(video), "-vf", scale,
        "-frames:v", "1", str(opening),
    ])
    if opening.exists():
        frames.append({"time": 0.0, "path": opening})

    # Scene-change frames. showinfo logs pts_time for each selected frame, in the
    # same order as the written files, so we zip the two together.
    pattern = str(workdir / "scene_%04d.jpg")
    r = run([
        "ffmpeg", "-y", "-i", str(video),
        "-vf", f"select='gt(scene,{scene_threshold})',showinfo,{scale}",
        "-vsync", "vfr", pattern,
    ])
    times = [float(m) for m in re.findall(r"pts_time:([0-9.]+)", r.stderr)]
    scene_files = sorted(workdir.glob("scene_*.jpg"))
    for t, f in zip(times, scene_files):
        frames.append({"time": t, "path": f})

    frames.sort(key=lambda x: x["time"])
    print(f"  {len(frames)} unique frames (1 opening + {len(scene_files)} scene changes).")
    return frames


VISION_PROMPT = (
    "Esta imagen es un fotograma de la grabación de una reunión de trabajo por "
    "Teams. Tu prioridad es el contenido compartido en pantalla (diapositiva, "
    "aplicación, documento, hoja de cálculo, navegador). Transcribe literalmente "
    "el texto legible de ese contenido (títulos, viñetas, etiquetas de interfaz, "
    "URL, cifras, celdas, encabezados) y describe brevemente su estado. Si solo "
    "se ven las cámaras de los participantes sin contenido compartido, indícalo "
    "en una sola línea con los nombres visibles. No describas la ropa ni la "
    "apariencia física de las personas. No inventes: si algo está borroso o "
    "ilegible, dilo. Sé conciso, máximo unas 8 líneas. Sin preámbulos ni "
    "conclusiones."
)


def describe_frame(client, vision_model: str, frame: dict) -> str:
    data = base64.standard_b64encode(frame["path"].read_bytes()).decode("utf-8")
    resp = client.messages.create(
        model=vision_model,
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/jpeg", "data": data}},
                {"type": "text", "text": VISION_PROMPT},
            ],
        }],
    )
    parts = [b.text for b in resp.content if b.type == "text"]
    return "\n".join(parts).strip()


def describe_frames(frames, vision_model: str, key: str, workers: int):
    import anthropic

    client = anthropic.Anthropic(api_key=key)
    print(f"Reading {len(frames)} frames with {vision_model}...")

    def work(idx_frame):
        idx, frame = idx_frame
        try:
            desc = describe_frame(client, vision_model, frame)
        except Exception as exc:  # noqa: BLE001
            desc = f"(no se pudo leer este fotograma: {exc})"
        print(f"  frame {idx + 1}/{len(frames)} @ {fmt_ts(frame['time'])}")
        return idx, desc

    descriptions = [""] * len(frames)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for idx, desc in pool.map(work, enumerate(frames)):
            descriptions[idx] = desc
    return descriptions


# ----------------------------- output ----------------------------------------

def segments_between(segments, start, end):
    return [s for s in segments if start <= s["start"] < end]


def build_markdown(video: Path, duration: float, segments, frames, descriptions,
                   whisper_model: str, vision_model: str | None, today: str) -> str:
    lines = []
    lines.append("---")
    lines.append(f'date: "{today}"')
    lines.append("tags:")
    lines.append("  - type/meeting-notes")
    lines.append("  - lang/es")
    lines.append("  - source/transcription")
    lines.append("---")
    lines.append("")
    lines.append(f"# Transcripción: {video.stem}")
    lines.append("")
    lines.append("> [!info] Procedencia")
    vis = vision_model if vision_model else "sin lectura de pantalla"
    lines.append(
        f"> Generado a partir de `{video.name}` ({fmt_ts(duration)}). "
        f"Audio: Whisper `{whisper_model}`. Pantalla: {vis}. "
        "Transcripción automática, revisar antes de citar."
    )
    lines.append("")

    if frames and descriptions:
        lines.append("## Línea de tiempo (voz y pantalla)")
        lines.append("")
        lines.append(
            "Cada bloque abre con lo que aparecía en pantalla y debajo recoge lo "
            "que se dijo mientras esa pantalla estaba visible."
        )
        lines.append("")
        for i, frame in enumerate(frames):
            t = frame["time"]
            next_t = frames[i + 1]["time"] if i + 1 < len(frames) else duration + 1
            lines.append(f"### [{fmt_ts(t)}] Pantalla {i + 1}")
            lines.append("")
            lines.append(f"**En pantalla:** {descriptions[i]}")
            lines.append("")
            spoken = segments_between(segments, t, next_t)
            if spoken:
                lines.append("**Se dijo:**")
                lines.append("")
                for s in spoken:
                    lines.append(f"- `[{fmt_ts(s['start'])}]` {s['text']}")
                lines.append("")
            else:
                lines.append("_(sin diálogo registrado en este tramo)_")
                lines.append("")

        lines.append("---")
        lines.append("")

    lines.append("## Transcripción completa")
    lines.append("")
    if segments:
        for s in segments:
            lines.append(f"`[{fmt_ts(s['start'])}]` {s['text']}")
            lines.append("")
    else:
        lines.append("_(sin audio transcrito)_")
        lines.append("")

    return "\n".join(lines)


# ----------------------------- main ------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Transcribe a meeting video with on-screen content.")
    ap.add_argument("video", help="Path to the meeting video (mp4, mov, mkv, ...)")
    ap.add_argument("--whisper-model", default="medium",
                    help="Whisper model size (tiny/base/small/medium/large). Default: medium")
    ap.add_argument("--language", default="es", help="Spoken language code. Default: es")
    ap.add_argument("--scene-threshold", type=float, default=0.3,
                    help="Scene-change sensitivity 0-1 (lower = more frames). Default: 0.3")
    ap.add_argument("--vision-model", default="claude-sonnet-4-6",
                    help="Claude model for reading frames. Default: claude-sonnet-4-6")
    ap.add_argument("--max-long-edge", type=int, default=1568,
                    help="Downscale frames to this long edge before sending. Default: 1568")
    ap.add_argument("--workers", type=int, default=4,
                    help="Concurrent vision requests. Default: 4")
    ap.add_argument("--no-vision", action="store_true", help="Audio only, skip on-screen reading.")
    ap.add_argument("--max-seconds", type=float, default=None,
                    help="Only process the first N seconds (for a quick quality test).")
    ap.add_argument("--output", default=None,
                    help="Output .md path. Default: alongside the video.")
    args = ap.parse_args()

    video = Path(args.video).expanduser()
    if not video.exists():
        sys.exit(f"Video not found: {video}")

    today = subprocess.run(["date", "+%Y-%m-%d"], capture_output=True, text=True).stdout.strip()

    key = None
    if not args.no_vision:
        key = get_anthropic_key()
        if not key:
            print("No Anthropic key (set ANTHROPIC_API_KEY or `secret anthropic`). "
                  "Falling back to audio only.")

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        source = video

        # Optional test slice.
        if args.max_seconds:
            sliced = workdir / f"slice{video.suffix}"
            print(f"Cutting a {args.max_seconds:.0f}s test slice...")
            run(["ffmpeg", "-y", "-i", str(video), "-t", str(args.max_seconds),
                 "-c", "copy", str(sliced)])
            if not sliced.exists() or sliced.stat().st_size == 0:
                # Re-encode fallback if stream copy failed on the cut point.
                run(["ffmpeg", "-y", "-i", str(video), "-t", str(args.max_seconds), str(sliced)])
            source = sliced

        duration = ffprobe_duration(source)
        print(f"Duration: {fmt_ts(duration)}")

        segments = transcribe_audio(source, args.whisper_model, args.language)

        frames, descriptions = [], []
        if not args.no_vision and key:
            frames = extract_frames(source, workdir, args.scene_threshold, args.max_long_edge)
            if frames:
                descriptions = describe_frames(frames, args.vision_model, key, args.workers)

        md = build_markdown(
            video, duration, segments, frames, descriptions,
            args.whisper_model, (args.vision_model if (frames and key) else None), today,
        )

    if args.output:
        out = Path(args.output).expanduser()
    else:
        suffix = " - Transcripción.md"
        out = video.with_name(video.stem + suffix)
    out.write_text(md, encoding="utf-8")
    print(f"\nWritten: {out}")


if __name__ == "__main__":
    main()
