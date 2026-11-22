"""Export unchanged animation frames without redundant rasterization."""

from __future__ import annotations

from io import BytesIO
from typing import Callable

from matplotlib.animation import FFMpegWriter, FuncAnimation


class VideoAnimation(FuncAnimation):
    def __init__(self, *args, content_frames: list[int], **kwargs):
        self.content_frames = content_frames
        self.content_frame: int | None = None
        super().__init__(*args, **kwargs)

    def _draw_frame(self, framedata):
        super()._draw_frame(framedata)
        self.content_frame = self.content_frames[framedata]

    def _post_draw(self, framedata, blit):
        # Animation.save's writer draws the figure in grab_frame. Interactive
        # playback still needs the normal canvas refresh.
        if not self._fig.canvas.is_saving():
            super()._post_draw(framedata, blit)


class CachedFrameFFMpegWriter(FFMpegWriter):
    def __init__(self, *args, content_frame: Callable[[], int | None], **kwargs):
        self._content_frame = content_frame
        self._cached_key: int | None = None
        self._cached_frame: bytes | None = None
        super().__init__(*args, **kwargs)

    def setup(self, *args, **kwargs):
        self._cached_key = None
        self._cached_frame = None
        return super().setup(*args, **kwargs)

    def grab_frame(self, **savefig_kwargs):
        key = self._content_frame()
        if key is None or key != self._cached_key or self._cached_frame is None:
            self.fig.set_size_inches(self._w, self._h)
            buffer = BytesIO()
            self.fig.savefig(buffer, format=self.frame_format, dpi=self.dpi, **savefig_kwargs)
            self._cached_frame = buffer.getvalue()
            self._cached_key = key
        # Repeating the original raw bytes preserves the hold's frame count,
        # timing and exact pixels while retaining the same encoder settings.
        self._proc.stdin.write(self._cached_frame)
