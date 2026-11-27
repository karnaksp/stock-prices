def pdm_build_update_files(context, files):
    if context.target == "wheel":
        files["stock_prices/_internal/demo-sber-lkoh.mp4"] = (
            context.root / "docs" / "assets" / "demo-sber-lkoh.mp4"
        )
