#!/usr/bin/env python3
"""
Тестовый скрипт для функциональности наложения
"""

from lib.overlay import add_overlay_video


def main():
    """
    Основная функция теста
    """
    # Тест с одним из существующих анимаций
    print("Тестирование функции наложения...")
    
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
        print("Тест завершен успешно!")
    except Exception as e:
        print(f"Тест завершился с ошибкой: {e}")


if __name__ == "__main__":
    main()