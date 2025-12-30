#!/usr/bin/env python3
"""
Test script for the overlay functionality
"""

from lib.overlay import add_overlay_video


def main():
    # Test with one of the existing animations
    print("Testing overlay function...")
    
    try:
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
        print("Test completed successfully!")
    except Exception as e:
        print(f"Test failed with error: {e}")


if __name__ == "__main__":
    main()