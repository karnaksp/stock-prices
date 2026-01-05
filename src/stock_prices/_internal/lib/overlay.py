"""
Модуль для наложения видео
"""

from moviepy.video.io.VideoFileClip import VideoFileClip
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
    """
    Добавляет оверлей к видео графика

    Args:
        graph_path: Путь к видео с графиком
        green_path: Путь к видео с зеленым фоном
        output_path: Путь для сохранения результата
        pos: Позиция оверлея
        scale: Масштаб оверлея
        opacity: Прозрачность оверлея
        color_to_remove: Цвет для удаления (зеленый фон)
        threshold: Порог чувствительности для удаления цвета
    """
    graph_clip = VideoFileClip(graph_path)
    green_clip = VideoFileClip(green_path).resize(scale)

    def mask_fn(gf, t):
        frame = gf(t).astype(float)
        dist = np.sqrt(np.sum((frame - color_to_remove) ** 2, axis=2))
        mask = np.clip(dist / threshold, 0, 1)
        mask = mask * opacity
        return mask

    from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip

    mask_clip = (
        VideoFileClip(green_path)
        .resize(scale)
        .to_mask(lambda frame: np.ones((frame.shape[0], frame.shape[1])))
    )

    masked_green = green_clip.set_mask(mask_clip)

    masked_green = masked_green.set_position(pos)

    final = CompositeVideoClip(
        [graph_clip, masked_green.set_duration(graph_clip.duration)]
    )

    final.write_videofile(
        output_path, codec="libx264", fps=graph_clip.fps, preset="medium", threads=4
    )


def moving_pos(t):
    """
    Возвращает движущуюся позицию
    Args:
        t: Время
    Returns:
        Позиция (x, y)
    """
    return (50 + 10 * t, 1480)


# Пример использования
# add_overlay_video(
#     "animations/IMOEX_000001_SS.mp4",
#     "cat_green.mp4",
#     "graph_with_green.mp4",
#     pos=moving_pos(13),
#     scale=0.3,
#     opacity=0.6,
#     color_to_remove=(0, 255, 1),
#     threshold=60,
# )
