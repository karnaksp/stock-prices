from io import BytesIO
from types import MethodType, SimpleNamespace

import matplotlib.pyplot as plt
from matplotlib.animation import FFMpegWriter, FuncAnimation
import pandas as pd
import pytest

from stock_prices._internal.lib.plotting import create_multi_line_animation
from stock_prices._internal.rendering.video_export import CachedFrameFFMpegWriter


class RawCapture:
    def _run(self):
        self.raw = BytesIO()
        self._proc = SimpleNamespace(stdin=self.raw)

    def finish(self):
        pass


class ReferenceWriter(RawCapture, FFMpegWriter):
    pass


class OptimizedWriter(RawCapture, CachedFrameFFMpegWriter):
    pass


def sample_animation(gradient, theme):
    data = pd.DataFrame({
        "TRADEDATE": pd.date_range("2020-01-01", periods=12),
        "CAPITAL_REINVEST": [100, 104, 96, 120, 130, 99, 110, 142, 135, 160, 150, 170],
        "DIVIDEND": [0, 0, 2, 0, 0, 0, 0, 3, 0, 0, 0, 0],
        "savings": [100] * 12,
        "EVENT_NAME": [None, None, "Event", "Event", None, None, None, None, None, None, None, None],
        "EVENT_IMPACT": [0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0],
    })
    invested = data.copy()
    invested["CAPITAL_REINVEST"] = invested["savings"]
    return create_multi_line_animation(
        [{"name": "TEST", "color": "#FFD166", "data": data},
         {"name": "Invested", "color": "#5B8CFF", "data": invested}],
        value_column="CAPITAL_REINVEST", target_duration=1, fps=4,
        final_frame_duration=1, use_gradient=gradient, theme=theme,
        title="Quality test", under_title="Dividends and events",
    )


@pytest.mark.parametrize("gradient", [False, True])
@pytest.mark.parametrize("theme", ["default", "studio", "aurora"])
def test_export_preserves_every_pixel_frame_and_hold(tmp_path, gradient, theme):
    outputs = []
    draw_counts = []
    for optimized in [False, True]:
        anim = sample_animation(gradient, theme)
        if not optimized:
            anim._post_draw = MethodType(FuncAnimation._post_draw, anim)
        writer = (OptimizedWriter(fps=4, content_frame=lambda: anim.content_frame)
                  if optimized else ReferenceWriter(fps=4))
        count = [0]
        original_draw = anim._fig.draw

        def draw(*args, **kwargs):
            count[0] += 1
            return original_draw(*args, **kwargs)

        anim._fig.draw = draw
        try:
            anim.save(tmp_path / "capture", writer=writer, dpi=12)
            outputs.append(writer.raw.getvalue())
            draw_counts.append(count[0])
        finally:
            plt.close(anim._fig)
    assert outputs[0] == outputs[1]
    assert len(outputs[1]) == 8 * 108 * 192 * 4
    assert draw_counts == [16, 4]


def test_interactive_animation_still_refreshes_the_canvas():
    anim = sample_animation(True, "default")
    draws = []
    original = anim._fig.canvas.draw_idle
    anim._fig.canvas.draw_idle = lambda: draws.append(True)
    try:
        anim._draw_next_frame(1, blit=False)
        assert draws == [True]
    finally:
        anim._draw_was_started = True
        anim._fig.canvas.draw_idle = original
        plt.close(anim._fig)


def test_writer_cache_is_reset_between_videos(tmp_path):
    writer = OptimizedWriter(fps=4, content_frame=lambda: 0)
    frames = []
    for color in ["red", "blue"]:
        fig = plt.figure(figsize=(1, 1), dpi=12, facecolor=color)
        try:
            with writer.saving(fig, tmp_path / "capture", dpi=12):
                writer.grab_frame()
                frames.append(writer.raw.getvalue())
        finally:
            plt.close(fig)
    assert frames[0] != frames[1]
