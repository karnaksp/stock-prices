from moviepy.video.io.VideoFileClip import VideoFileClip
from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
from moviepy.video.VideoClip import VideoClip
from moviepy.video.fx import Loop
import numpy as np


def add_overlay_video(
    graph_path: str,
    green_path: str,
    output_path: str,
    pos=("center", "center"),
    scale: float = 2.0,
    opacity: float = 0.6,
    color_to_remove=(0, 255, 0),
    threshold: float = 60,
):
    # Основной фон
    graph_clip = VideoFileClip(graph_path)

    # Видео с зеленым фоном
    green_clip = VideoFileClip(green_path).resized(scale)
    green_clip = Loop(duration=graph_clip.duration).apply(green_clip)

    # Создаем маску (1 = видим, 0 = прозрачный)
    def mask_fn(t):
        frame = green_clip.get_frame(t).astype(float)
        dist = np.sqrt(np.sum((frame - color_to_remove) ** 2, axis=2))
        mask = np.clip(dist / threshold, 0, 1)  # растягиваем 0..1
        mask = mask * opacity  # делаем полупрозрачным
        return mask

    # Оборачиваем видео в VideoClip с маской
    masked_green = VideoClip(
        frame_function=lambda t: green_clip.get_frame(t), duration=green_clip.duration
    )

    mask_clip = VideoClip(
        frame_function=lambda t: mask_fn(t),
        is_mask=True,
        duration=green_clip.duration,
    )
    masked_green = masked_green.with_mask(mask_clip)

    # Позиция и продолжительность
    masked_green = masked_green.with_position(pos).with_duration(graph_clip.duration)

    # Композит
    final = CompositeVideoClip([graph_clip, masked_green])

    # Сохраняем
    final.write_videofile(
        output_path, codec="libx264", fps=graph_clip.fps, preset="medium", threads=4
    )


def moving_pos(t):
    # x: двигается слева направо, y: всегда
    return (50 + 10 * t, 1480)


# Пример использования
add_overlay_video(
    "animations/IMOEX_000001_SS.mp4",
    "cat_green.mp4",
    "graph_with_green.mp4",
    pos=moving_pos(13),
    scale=0.3,
    opacity=0.6,
    color_to_remove=(0, 255, 1),
    threshold=60,
)
