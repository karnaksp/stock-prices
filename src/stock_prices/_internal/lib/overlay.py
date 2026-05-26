from __future__ import annotations

import subprocess
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe


def _position_expr(pos) -> tuple[str, str]:
    if isinstance(pos, tuple) and len(pos) == 2 and all(isinstance(value, (int, float)) for value in pos):
        return str(int(pos[0])), str(int(pos[1]))
    if pos == ("center", "center"):
        return "(W-w)/2", "(H-h)/2"
    if pos == ("center", "bottom"):
        return "(W-w)/2", "H-h"
    if pos == ("center", "top"):
        return "(W-w)/2", "0"
    if pos == ("left", "bottom"):
        return "0", "H-h"
    return "(W-w)/2", "(H-h)/2"


def add_overlay_video(
    graph_path: str,
    green_path: str,
    output_path: str,
    pos=("center", "center"),
    scale: float = 1.0,
    opacity: float = 0.6,
    color_to_remove=(0, 255, 0),
    threshold: float = 60,
) -> None:
    graph = Path(graph_path)
    overlay = Path(green_path)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    x_expr, y_expr = _position_expr(pos)
    color = "0x%02x%02x%02x" % tuple(color_to_remove)
    similarity = max(0.01, min(float(threshold) / 255.0, 1.0))
    alpha = max(0.0, min(opacity, 1.0))
    filter_complex = (
        f"[1:v]scale=iw*{scale}:ih*{scale},chromakey={color}:{similarity}:0.08,"
        f"format=rgba,colorchannelmixer=aa={alpha}[ov];"
        f"[0:v][ov]overlay={x_expr}:{y_expr}:shortest=1[v]"
    )
    command = [
        get_ffmpeg_exe(),
        "-y",
        "-i",
        str(graph),
        "-i",
        str(overlay),
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-preset",
        "veryfast",
        "-crf",
        "21",
        str(output),
    ]
    subprocess.run(command, check=True, capture_output=True)


def moving_pos(t: float) -> tuple[int, int]:
    return (50 + int(10 * t), 1480)
