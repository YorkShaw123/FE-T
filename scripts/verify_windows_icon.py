# -*- coding: utf-8 -*-
"""验证 canonical PNG 与 Windows ICO 各帧的一致性，并导出可视化样本。"""
from __future__ import annotations

from pathlib import Path

from PIL import IcoImagePlugin, Image, ImageChops, ImageStat


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "assets" / "icon-reference-512.png"
ICO = ROOT / "src-tauri" / "icons" / "icon.ico"
OUTPUT_DIR = ROOT / "build" / "icon-verification"
REQUIRED_SIZES = ((16, 16), (32, 32), (48, 48), (256, 256))


def _center_of_mass(image: Image.Image) -> tuple[float, float]:
    alpha = image.getchannel("A")
    pixels = alpha.load()
    total = sum(pixels[x, y] for y in range(image.height) for x in range(image.width))
    if not total:
        return 0.0, 0.0
    x_mass = sum(
        x * pixels[x, y] for y in range(image.height) for x in range(image.width)
    )
    y_mass = sum(
        y * pixels[x, y] for y in range(image.height) for x in range(image.width)
    )
    return x_mass / total, y_mass / total


def main() -> None:
    canonical = Image.open(CANONICAL).convert("RGBA")
    if canonical.size != (512, 512):
        raise SystemExit(f"canonical 尺寸错误: {canonical.size}")
    if canonical.mode != "RGBA":
        raise SystemExit(f"canonical 模式错误: {canonical.mode}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with ICO.open("rb") as stream:
        ico = IcoImagePlugin.IcoFile(stream)
        available = ico.sizes()
        missing = set(REQUIRED_SIZES) - available
        if missing:
            raise SystemExit(f"ICO 缺少尺寸: {sorted(missing)}")

        for size in REQUIRED_SIZES:
            extracted = ico.getimage(size).convert("RGBA")
            expected = canonical.resize(size, Image.Resampling.LANCZOS)
            extracted.save(OUTPUT_DIR / f"ico-{size[0]}.png")
            expected.save(OUTPUT_DIR / f"canonical-{size[0]}.png")

            difference = ImageChops.difference(extracted, expected)
            mean_error = sum(ImageStat.Stat(difference).mean) / 4
            alpha_bbox_matches = extracted.getchannel("A").getbbox() == expected.getchannel("A").getbbox()
            ex_center = _center_of_mass(extracted)
            ref_center = _center_of_mass(expected)
            center_delta = ((ex_center[0] - ref_center[0]) ** 2 + (ex_center[1] - ref_center[1]) ** 2) ** 0.5
            if mean_error > 1.0 or not alpha_bbox_matches or center_delta > 0.1:
                raise SystemExit(
                    f"ICO {size[0]}px 与 canonical 不一致: "
                    f"MAE={mean_error:.4f}, alpha_bbox={alpha_bbox_matches}, "
                    f"center_delta={center_delta:.4f}"
                )
            print(
                f"{size[0]}px OK: MAE={mean_error:.4f}, "
                f"alpha_bbox={alpha_bbox_matches}, center_delta={center_delta:.4f}"
            )


if __name__ == "__main__":
    main()
