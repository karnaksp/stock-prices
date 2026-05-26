---
title: API
hide:
- navigation
---

# API

Публичный Python API позволяет запускать тот же pipeline генерации видео, который используют CLI и Telegram-бот.

```python
from datetime import date

from stock_prices import RenderSettings, TickerSpec, VideoRequest, generate_video

path = generate_video(
    VideoRequest(
        ticker_specs=[TickerSpec("SBER"), TickerSpec("LKOH")],
        render=RenderSettings(
            start_date=date(2020, 1, 1),
            end_date=date(2024, 12, 31),
            duration=20,
            fps=20,
        ),
    )
)
print(path)
```

::: stock_prices
