from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChartTheme:
    name: str
    figure_bg: str
    axes_bg: str
    grid_color: str
    axis_color: str
    spine_color: str
    title_color: str
    subtitle_color: str
    muted_color: str
    date_box_bg: str
    date_box_edge: str
    label_box_bg: str
    footer_color: str
    invested_color: str
    palette: tuple[str, ...]


DEFAULT_PALETTE = (
    "#FFD166",
    "#00D1B2",
    "#5B8CFF",
    "#EF476F",
    "#B36BFF",
    "#FF8A3D",
    "#2EC4B6",
    "#E9C46A",
    "#4D96FF",
    "#FF6B6B",
    "#7BD88F",
    "#C77DFF",
    "#F4A261",
    "#48CAE4",
    "#F72585",
    "#A3E635",
)

THEMES: dict[str, ChartTheme] = {
    "default": ChartTheme(
        name="default",
        figure_bg="#0D0E11",
        axes_bg="#15171C",
        grid_color="#B6BCC6",
        axis_color="#B6BCC6",
        spine_color="#343942",
        title_color="#f8fafc",
        subtitle_color="#A2A9B3",
        muted_color="#858B96",
        date_box_bg="#0D0E11",
        date_box_edge="#343942",
        label_box_bg="#10131a",
        footer_color="#595F6B",
        invested_color="#8f9aa8",
        palette=DEFAULT_PALETTE,
    ),
    "aurora": ChartTheme(
        name="aurora",
        figure_bg="#090D10",
        axes_bg="#11181D",
        grid_color="#9FB7B3",
        axis_color="#B8C7C4",
        spine_color="#28464C",
        title_color="#F6FFF8",
        subtitle_color="#AFC8C0",
        muted_color="#7B918B",
        date_box_bg="#0A1114",
        date_box_edge="#2B6F6A",
        label_box_bg="#081216",
        footer_color="#54706B",
        invested_color="#95A3B3",
        palette=("#80ED99", "#48CAE4", "#FFD166", "#FF70A6", "#B388EB", "#F8961E", "#43AA8B", "#577590"),
    ),
    "studio": ChartTheme(
        name="studio",
        figure_bg="#0B0B0F",
        axes_bg="#16151A",
        grid_color="#B8B1C4",
        axis_color="#C7C1D2",
        spine_color="#3D3748",
        title_color="#FAFAFF",
        subtitle_color="#B4ACBF",
        muted_color="#888293",
        date_box_bg="#101016",
        date_box_edge="#4A4358",
        label_box_bg="#121019",
        footer_color="#686172",
        invested_color="#9BA3AF",
        palette=("#F4D35E", "#33C7A7", "#6C8DFF", "#F95738", "#B565F2", "#F6A04D", "#4CC9F0", "#90BE6D"),
    ),
}


def get_theme_names() -> tuple[str, ...]:
    return tuple(THEMES)


def get_chart_theme(name: str | None) -> ChartTheme:
    key = (name or "default").strip().lower()
    if key not in THEMES:
        options = ", ".join(get_theme_names())
        raise ValueError(f"Unknown chart theme '{name}'. Use one of: {options}.")
    return THEMES[key]
