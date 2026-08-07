# -*- coding: utf-8 -*-
"""生成应用图标源图（1024x1024 PNG），供 `npx tauri icon` 生成全套图标。

图形与 Web 端 favicon.svg 保持一致：深色圆角底 + 青绿色线描的三层树。
用法：python scripts/generate-icon.py
产物：assets/app-icon.png
"""
import os

from PIL import Image, ImageDraw

SIZE = 1024
VIEWBOX = 38  # favicon.svg 的视口尺寸
SCALE = SIZE / VIEWBOX

# favicon.svg 配色
TILE = (16, 32, 26)     # 深色圆角底 #10201a
TREE = (20, 155, 120)   # 青绿 #149b78

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets', 'app-icon.png')


def cubic(p0, p1, p2, p3, n=160):
    """把三次贝塞尔曲线采样为点序列（PIL 无内建贝塞尔）"""
    pts = []
    for i in range(n + 1):
        t = i / n
        mt = 1 - t
        x = mt ** 3 * p0[0] + 3 * mt ** 2 * t * p1[0] + 3 * mt * t ** 2 * p2[0] + t ** 3 * p3[0]
        y = mt ** 3 * p0[1] + 3 * mt ** 2 * t * p1[1] + 3 * mt * t ** 2 * p2[1] + t ** 3 * p3[1]
        pts.append((x * SCALE, y * SCALE))
    return pts


def main():
    img = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 圆角深色底（rx=12/38，与 favicon 一致）
    radius = int(12 / VIEWBOX * SIZE)
    draw.rounded_rectangle([0, 0, SIZE, SIZE], radius=radius, fill=TILE)

    # 三层树冠（线描贝塞尔曲线，stroke-width≈1.5/38*SIZE）
    line_width = max(2, int(1.5 / VIEWBOX * SIZE))
    curves = [
        ((8.0, 30.3), (13.8, 26.2), (21.2, 25.3), (30.0, 27.4)),
        ((12.0, 24.3), (16.8, 20.9), (22.8, 20.2), (30.0, 21.9)),
        ((17.0, 18.2), (20.5, 15.8), (24.8, 15.3), (30.0, 16.5)),
    ]
    for p0, p1, p2, p3 in curves:
        draw.line(cubic(p0, p1, p2, p3), fill=TREE, width=line_width, joint='curve')

    # 树干（填充多边形）
    trunk = [(x * SCALE, y * SCALE) for x, y in [(17.8, 31.7), (21.0, 8.5), (23.0, 8.8), (19.8, 31.9)]]
    draw.polygon(trunk, fill=TREE)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    img.save(OUT, 'PNG')
    print(f'图标源图已生成: {OUT}')


if __name__ == '__main__':
    main()
