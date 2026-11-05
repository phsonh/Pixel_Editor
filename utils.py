import math

from PyQt5.QtGui import QColor, QImage, QPainter


COLOR_BLEND_MODES = {
    "normal": QPainter.CompositionMode_SourceOver,
    "multiply": QPainter.CompositionMode_Multiply,
    "screen": QPainter.CompositionMode_Screen,
    "overlay": QPainter.CompositionMode_Overlay,
    "soft_light": QPainter.CompositionMode_SoftLight,
    "hard_light": QPainter.CompositionMode_HardLight,
    "darken": QPainter.CompositionMode_Darken,
    "lighten": QPainter.CompositionMode_Lighten,
    "color_dodge": QPainter.CompositionMode_ColorDodge,
    "color_burn": QPainter.CompositionMode_ColorBurn,
    "difference": QPainter.CompositionMode_Difference,
    "plus": QPainter.CompositionMode_Plus,
}


def blend_color_image(source, color, blend_mode="normal"):
    """Blend a solid color into an image while preserving its alpha mask."""
    if source.isNull():
        return QImage()

    color = QColor(color)
    if not color.isValid():
        return source.copy()

    if blend_mode == "replace":
        result = QImage(
            source.size(), QImage.Format_ARGB32_Premultiplied
        )
        result.fill(color)
        return result

    if color.alpha() == 0:
        return source.copy()

    source_argb = source.convertToFormat(QImage.Format_ARGB32_Premultiplied)

    # Blend against opaque RGB first, then restore the exact source alpha.
    # This treats the color as clipped to the selected artwork instead of
    # filling transparent pixels inside its rectangular selection.
    result = source_argb.convertToFormat(QImage.Format_RGB32)
    opaque_color = QColor(color)
    opaque_color.setAlpha(255)
    painter = QPainter(result)
    painter.setOpacity(color.alphaF())
    painter.setCompositionMode(
        COLOR_BLEND_MODES.get(
            blend_mode, QPainter.CompositionMode_SourceOver
        )
    )
    painter.fillRect(result.rect(), opaque_color)
    painter.end()

    result = result.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    painter = QPainter(result)
    painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    painter.drawImage(0, 0, source_argb)
    painter.end()
    return result

def get_grid_pos(wx, wy):
    """世界坐标转网格坐标 (向下取整)"""
    return math.floor(wx), math.floor(wy)

def get_intersection_pos(wx, wy):
    """世界坐标转交点坐标 (四舍五入)"""
    return round(wx), round(wy)

def get_bresenham_line(x0, y0, x1, y1):
    """Bresenham 直线算法，返回两点间所有整数点"""
    points = []
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    
    while True:
        points.append((x0, y0))
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy
    return points
