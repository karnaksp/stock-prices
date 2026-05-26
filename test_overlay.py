from __future__ import annotations

from stock_prices._internal.lib.overlay import add_overlay_video


def main() -> None:
    add_overlay_video(
        "animations/AAPL_SBER.mp4",
        "cat_green.mp4",
        "test_output.mp4",
        pos=("center", "bottom"),
        scale=2.0,
        opacity=0.6,
        color_to_remove=(0, 255, 0),
        threshold=60,
    )


if __name__ == "__main__":
    main()
