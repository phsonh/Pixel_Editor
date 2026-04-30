import math

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