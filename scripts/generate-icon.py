# -*- coding: utf-8 -*-
"""从网页顶栏 ``.brand-mark`` 的 CSS 几何生成 Windows 图标。

网页组件是唯一视觉基准。脚本先生成唯一 canonical RGBA PNG，再由该 PNG
缩放出所有 Windows 尺寸；不会读取或修补任何旧 PNG/ICO。
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_PATH = ROOT / "assets" / "icon-reference-512.png"
ICONS_DIR = ROOT / "src-tauri" / "icons"

VIEWBOX = 38.0
CANONICAL_SIZE = 512
SUPERSAMPLE = 4

# style.css 暗色主题的最终计算颜色：.brand-mark 背景 var(--ink)，图形 var(--jade)
TILE_COLOR = (237, 245, 241, 255)  # #edf5f1
MARK_COLOR = (50, 201, 157, 255)  # #32c99d

ICO_SIZES = tuple((size, size) for size in (16, 32, 48, 64, 128, 256))


def _scale(value: float) -> float:
    return value * CANONICAL_SIZE * SUPERSAMPLE / VIEWBOX


def _rotate(
    point: tuple[float, float],
    center: tuple[float, float],
    degrees: float,
) -> tuple[float, float]:
    radians = math.radians(degrees)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    x, y = point
    cx, cy = center
    dx, dy = x - cx, y - cy
    return (
        cx + dx * cosine - dy * sine,
        cy + dx * sine + dy * cosine,
    )


def _draw_crown(
    image: Image.Image,
    bounds: tuple[float, float, float, float],
    stroke_width: int,
) -> Image.Image:
    """栅格化 CSS 圆角顶边，再围绕该盒子中心整体旋转 -8°。"""
    left, top, right, bottom = bounds
    center = (_scale((left + right) / 2), _scale((top + bottom) / 2))
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    layer_draw = ImageDraw.Draw(layer)
    layer_draw.arc(
        (_scale(left), _scale(top), _scale(right), _scale(bottom)),
        start=180,
        end=360,
        fill=MARK_COLOR,
        width=stroke_width,
    )
    # Pillow 正角度为逆时针，与 CSS rotate(-8deg) 在屏幕坐标中的视觉方向一致。
    layer = layer.rotate(8.0, resample=Image.Resampling.BICUBIC, center=center)
    return Image.alpha_composite(image, layer)


def _rotated_rectangle(
    bounds: tuple[float, float, float, float],
    degrees: float,
) -> list[tuple[float, float]]:
    left, top, right, bottom = bounds
    center = ((left + right) / 2, (top + bottom) / 2)
    corners = ((left, top), (right, top), (right, bottom), (left, bottom))
    return [
        (_scale(x), _scale(y))
        for x, y in (_rotate(point, center, degrees) for point in corners)
    ]


def render_canonical() -> Image.Image:
    canvas_size = CANONICAL_SIZE * SUPERSAMPLE
    image = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # .brand-mark: 38 × 38，border-radius: 12px，暗色主题背景 var(--ink)。
    draw.rounded_rectangle(
        (0, 0, canvas_size - 1, canvas_size - 1),
        radius=round(_scale(12)),
        fill=TILE_COLOR,
    )

    # ::before、span、::after 的实际 CSS 盒子：right 均为 8px、height 为 8px，
    # 只绘制 1.5px 顶边，border-radius: 50%，transform: rotate(-8deg)。
    crown_boxes = (
        (8.0, 23.0, 30.0, 31.0),
        (12.0, 17.0, 30.0, 25.0),
        (17.0, 11.0, 30.0, 19.0),
    )
    stroke_width = max(1, round(_scale(1.5)))
    for bounds in crown_boxes:
        image = _draw_crown(image, bounds, stroke_width)

    # .brand-mark i: left 18px、bottom 6px、2 × 23px，rotate(8deg)。
    draw = ImageDraw.Draw(image)
    draw.polygon(
        _rotated_rectangle((18.0, 9.0, 20.0, 32.0), 8.0),
        fill=MARK_COLOR,
    )

    return image.resize(
        (CANONICAL_SIZE, CANONICAL_SIZE),
        Image.Resampling.LANCZOS,
    )


def save_windows_assets(canonical: Image.Image) -> None:
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    CANONICAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    canonical.save(CANONICAL_PATH, "PNG")

    png_targets = {
        ICONS_DIR / "32x32.png": 32,
        ICONS_DIR / "64x64.png": 64,
        ICONS_DIR / "128x128.png": 128,
        ICONS_DIR / "128x128@2x.png": 256,
        ICONS_DIR / "icon.png": 512,
    }
    for path, size in png_targets.items():
        canonical.resize((size, size), Image.Resampling.LANCZOS).save(path, "PNG")

    # Pillow 只接受一个视觉输入；sizes 参数从 canonical 自动生成 ICO 帧。
    canonical.save(ICONS_DIR / "icon.ico", format="ICO", sizes=ICO_SIZES)


def main() -> None:
    canonical = render_canonical()
    save_windows_assets(canonical)
    print(f"Canonical PNG: {CANONICAL_PATH}")
    print(f"Windows ICO: {ICONS_DIR / 'icon.ico'}")


if __name__ == "__main__":
    main()
