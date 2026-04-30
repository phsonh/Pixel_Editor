import math
from PyQt5.QtWidgets import QWidget, QMenu
from PyQt5.QtGui import QPainter, QPen, QColor, QMouseEvent, QWheelEvent, QCursor
from PyQt5.QtCore import Qt, QPointF, QRectF, QPoint, QRect, QTimer

from consts import ToolType, DEFAULT_COLOR, BACKGROUND_COLOR
from utils import get_grid_pos, get_intersection_pos, get_bresenham_line
from model import EditorModel

RESIZE_NONE = 0
RESIZE_LEFT = 1
RESIZE_RIGHT = 2
RESIZE_TOP = 4      
RESIZE_BOTTOM = 8   

class TextureCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = EditorModel()
        
        self.zoom = 20.0
        self.offset_x = 0.0; self.offset_y = 0.0 
        self.min_zoom = 0.01; self.max_zoom = 1000.0
        self.current_tool = ToolType.PEN
        self.current_color = DEFAULT_COLOR
        
        self.last_mouse_pos = QPoint()
        self.last_grid_pos = None
        self.mouse_world_pos = (0, 0)
        
        self.is_selecting = False
        self.selection_start_grid = None
        
        self.is_moving_pixels = False
        self.move_start_world_pos = (0, 0)
        self.current_move_offset = (0, 0)
        
        self.resize_handle = RESIZE_NONE
        self.resize_start_rect = None 
        
        self.auto_scroll_timer = QTimer(self)
        self.auto_scroll_timer.timeout.connect(self.handle_auto_scroll)
        self.scroll_delta = (0, 0)
        
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def get_snap_step(self):
        """根据当前缩放计算对齐步长。视野越远，步长越大(8, 16, 32...)"""
        if self.zoom > 10: return 1
        step = 8
        while (step * self.zoom) < 30: # 确保屏幕上感官步长不小于30像素
            step *= 2
        return step

    def _get_snapped_pos(self, wx, wy):
        """获取对齐后的世界坐标和当前步长"""
        step = self.get_snap_step()
        ix = math.floor(wx / step) * step
        iy = math.floor(wy / step) * step
        return int(ix), int(iy), step

    def fit_to_rect(self, rect: QRect):
        if not rect or rect.isEmpty(): return
        margin = 0.9
        available_w = self.width() * margin
        available_h = self.height() * margin
        zoom_x = available_w / rect.width()
        zoom_y = available_h / rect.height()
        self.zoom = min(zoom_x, zoom_y)
        self.zoom = max(self.min_zoom, min(self.max_zoom, self.zoom))
        center_w_x = rect.x() + rect.width() / 2.0
        center_w_y = rect.y() + rect.height() / 2.0
        self.offset_x = -(center_w_x * self.zoom)
        self.offset_y = (center_w_y * self.zoom)
        self.update()

    def screen_to_world(self, sx, sy):
        cx = self.width() / 2; cy = self.height() / 2
        wx = (sx - cx - self.offset_x) / self.zoom; wy = (cy + self.offset_y - sy) / self.zoom
        return wx, wy

    def world_to_screen(self, wx, wy):
        cx = self.width() / 2; cy = self.height() / 2
        sx = (wx * self.zoom) + cx + self.offset_x; sy = cy + self.offset_y - (wy * self.zoom)
        return sx, sy

    def _get_resize_handle(self, wx, wy):
        rect = self.model.selection_rect
        if not rect or self.is_moving_pixels: return RESIZE_NONE
        margin = 8.0 / self.zoom # 稍微放大边缘判定
        l, r = rect.x(), rect.x() + rect.width()
        b, t = rect.y(), rect.y() + rect.height()
        handle = RESIZE_NONE
        if abs(wx - l) < margin: handle |= RESIZE_LEFT
        elif abs(wx - r) < margin: handle |= RESIZE_RIGHT
        if abs(wy - t) < margin: handle |= RESIZE_TOP
        elif abs(wy - b) < margin: handle |= RESIZE_BOTTOM
        return handle

    def _update_cursor_icon(self, handle, ix, iy):
        if handle == RESIZE_NONE:
            if self.current_tool == ToolType.SELECT:
                if self.model.selection_rect and self.model.selection_rect.contains(ix, iy):
                    self.setCursor(Qt.SizeAllCursor)
                else: self.setCursor(Qt.CrossCursor)
            else: self.setCursor(Qt.ArrowCursor)
            return
        if handle in (RESIZE_LEFT | RESIZE_TOP, RESIZE_RIGHT | RESIZE_BOTTOM):
            self.setCursor(Qt.SizeFDiagCursor)
        elif handle in (RESIZE_RIGHT | RESIZE_TOP, RESIZE_LEFT | RESIZE_BOTTOM):
            self.setCursor(Qt.SizeBDiagCursor)
        elif handle & (RESIZE_LEFT | RESIZE_RIGHT):
            self.setCursor(Qt.SizeHorCursor)
        elif handle & (RESIZE_TOP | RESIZE_BOTTOM):
            self.setCursor(Qt.SizeVerCursor)

    def mousePressEvent(self, event: QMouseEvent):
        self.last_mouse_pos = event.pos()
        wx, wy = self.screen_to_world(event.x(), event.y())
        ix, iy, step = self._get_snapped_pos(wx, wy)
        
        if event.button() == Qt.LeftButton:
            self.resize_handle = self._get_resize_handle(wx, wy)
            
            if self.resize_handle != RESIZE_NONE:
                self.model.push_undo_state()
                self.resize_start_rect = QRect(self.model.selection_rect) 
            elif self.current_tool == ToolType.POINT:
                if self.zoom > 10:
                    self.model.push_undo_state()
                    px, py = get_intersection_pos(wx, wy)
                    self.model.vector_points.add((px, py))
            elif self.current_tool in [ToolType.PEN, ToolType.ERASER]:
                pix_x, pix_y = get_grid_pos(wx, wy)
                if self.model.selection_rect and not self.model.selection_rect.contains(pix_x, pix_y):
                    if self.is_moving_pixels: 
                        self.model.drop_selection(0, 0)
                        self.is_moving_pixels = False
                    self.model.selection_rect = None
                else:
                    self.model.push_undo_state()
                    self._apply_tool_line(pix_x, pix_y, pix_x, pix_y)
                self.last_grid_pos = (pix_x, pix_y)
            elif self.current_tool == ToolType.SELECT:
                pix_x, pix_y = get_grid_pos(wx, wy)
                if self.model.selection_rect and self.model.selection_rect.contains(pix_x, pix_y):
                    if not self.is_moving_pixels:
                        self.model.push_undo_state()
                        self.is_moving_pixels = True
                        self.model.lift_selection()
                    self.move_start_world_pos = (wx, wy)
                    self.current_move_offset = (0, 0) 
                else:
                    if self.is_moving_pixels:
                        self.model.drop_selection(0, 0)
                        self.is_moving_pixels = False
                    self.is_selecting = True
                    self.selection_start_grid = (ix, iy)
                    self.model.selection_rect = QRect(ix, iy, step, step)
                    if self.parent() and hasattr(self.parent(), 'update_selection_ui'):
                        self.parent().update_selection_ui()
            self.update()
        elif event.button() == Qt.RightButton:
            self.show_context_menu(event.globalPos(), QPoint(int(wx), int(wy)))
        elif event.button() == Qt.MiddleButton:
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent):
        wx, wy = self.screen_to_world(event.x(), event.y())
        ix, iy, step = self._get_snapped_pos(wx, wy)
        self.mouse_world_pos = (wx, wy)
        
        if self.parent() and hasattr(self.parent(), 'update_mouse_status'): 
            self.parent().update_mouse_status(math.floor(wx), math.floor(wy), self.zoom)
            
        delta = event.pos() - self.last_mouse_pos
        
        if (event.buttons() & Qt.MiddleButton) or \
           (event.buttons() & Qt.RightButton and self.current_tool != ToolType.POINT and not self.model.selection_rect):
            self.offset_x += delta.x()
            self.offset_y += delta.y()
            
        if event.buttons() & Qt.LeftButton:
            if self.resize_handle != RESIZE_NONE:
                self._perform_resize(ix, iy)
                self.check_auto_scroll(event.pos())
            elif self.is_moving_pixels:
                start_wx, start_wy = self.move_start_world_pos
                dx = math.floor((wx - start_wx) / step + 0.5) * step
                dy = math.floor((wy - start_wy) / step + 0.5) * step
                self.current_move_offset = (dx, dy)
                self.check_auto_scroll(event.pos())
            elif self.is_selecting:
                self._update_selection(ix, iy)
                self.check_auto_scroll(event.pos())
            elif self.current_tool in [ToolType.PEN, ToolType.ERASER]:
                pix_x, pix_y = get_grid_pos(wx, wy)
                if self.last_grid_pos: 
                    self._apply_tool_line(*self.last_grid_pos, pix_x, pix_y)
                self.last_grid_pos = (pix_x, pix_y)
        else:
            handle = self._get_resize_handle(wx, wy)
            self._update_cursor_icon(handle, math.floor(wx), math.floor(wy))
            self.auto_scroll_timer.stop()

        self.last_mouse_pos = event.pos()
        self.update()

    def _perform_resize(self, ix, iy):
        if not self.resize_start_rect: return
        rect = self.resize_start_rect
        l, r = rect.x(), rect.x() + rect.width()
        b, t = rect.y(), rect.y() + rect.height()
        step = self.get_snap_step()
        
        if self.resize_handle & RESIZE_LEFT: l = ix
        if self.resize_handle & RESIZE_RIGHT: r = ix + step
        if self.resize_handle & RESIZE_BOTTOM: b = iy
        if self.resize_handle & RESIZE_TOP: t = iy + step
        
        new_x, new_y = min(l, r), min(b, t)
        new_w, new_h = max(step, abs(r - l)), max(step, abs(t - b))
        
        self.model.selection_rect = QRect(new_x, new_y, new_w, new_h)
        if self.parent() and hasattr(self.parent(), 'update_selection_ui'):
            self.parent().update_selection_ui()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self.auto_scroll_timer.isActive(): self.auto_scroll_timer.stop()
        if event.button() == Qt.LeftButton:
            self.resize_handle = RESIZE_NONE
            self.resize_start_rect = None
            self.is_selecting = False
            if self.is_moving_pixels:
                self.is_moving_pixels = False
                self.model.drop_selection(*self.current_move_offset)
                self.current_move_offset = (0, 0)
                if self.parent() and hasattr(self.parent(), 'update_selection_ui'):
                    self.parent().update_selection_ui()
        self.setCursor(Qt.ArrowCursor)
        self.update()

    def _update_selection(self, ix, iy):
        if self.selection_start_grid is None: return
        sx, sy = self.selection_start_grid
        step = self.get_snap_step()
        x1, x2 = min(sx, ix), max(sx, ix); y1, y2 = min(sy, iy), max(sy, iy)
        self.model.selection_rect = QRect(x1, y1, x2 - x1 + step, y2 - y1 + step)
        if self.parent() and hasattr(self.parent(), 'update_selection_ui'):
            self.parent().update_selection_ui()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), BACKGROUND_COLOR)
        left_w, top_w = self.screen_to_world(0, 0)
        right_w, bottom_w = self.screen_to_world(self.width(), self.height())
        v_min_x, v_max_x = min(left_w, right_w), max(left_w, right_w)
        v_min_y, v_max_y = min(bottom_w, top_w), max(bottom_w, top_w)
        
        self._draw_grid(painter, v_min_x, v_max_x, v_min_y, v_max_y)
        self._draw_main_layer(painter)
        self._draw_floating_layer(painter)
        self._draw_json_regions(painter) 
        self._draw_vector_points(painter, v_min_x, v_max_x, v_min_y, v_max_y)
        if self.model.selection_rect: self._draw_selection_rect(painter)
        self._draw_cursor(painter)

    def _draw_grid(self, p, min_x, max_x, min_y, max_y):
        if self.zoom > 5:
            p.setPen(QPen(QColor(50, 50, 50), 1))
            for x in range(math.floor(min_x), math.ceil(max_x) + 1):
                sx, _ = self.world_to_screen(x, 0); p.drawLine(int(sx), 0, int(sx), self.height())
            for y in range(math.floor(min_y), math.ceil(max_y) + 1):
                _, sy = self.world_to_screen(0, y); p.drawLine(0, int(sy), self.width(), int(sy))
        step = 8
        while (step * self.zoom) < 64: step *= 2
        for x in range(math.floor(min_x/step)*step, math.ceil(max_x/step)*step + 1, step):
            sx, _ = self.world_to_screen(x, 0); p.setPen(QPen(QColor(200, 200, 200), 2) if x == 0 else QPen(QColor(90, 90, 90), 1))
            p.drawLine(int(sx), 0, int(sx), self.height())
        for y in range(math.floor(min_y/step)*step, math.ceil(max_y/step)*step + 1, step):
            _, sy = self.world_to_screen(0, y); p.setPen(QPen(QColor(200, 200, 200), 2) if y == 0 else QPen(QColor(90, 90, 90), 1))
            p.drawLine(0, int(sy), self.width(), int(sy))

    def _draw_main_layer(self, p):
        ox, oy = self.model.layer_origin.x(), self.model.layer_origin.y()
        img = self.model.main_layer; w, h = img.width(), img.height()
        tl_sx, tl_sy = self.world_to_screen(ox, oy + h); br_sx, br_sy = self.world_to_screen(ox + w, oy)
        p.drawImage(QRectF(QPointF(tl_sx, tl_sy), QPointF(br_sx, br_sy)), img)

    def _draw_floating_layer(self, p):
        if self.is_moving_pixels and self.model.floating_layer:
            dx, dy = self.current_move_offset; rect = self.model.selection_rect
            f_img = self.model.floating_layer; w, h = f_img.width(), f_img.height()
            tl_sx, tl_sy = self.world_to_screen(rect.x() + dx, rect.y() + dy + h)
            br_sx, br_sy = self.world_to_screen(rect.x() + dx + w, rect.y() + dy)
            p.drawImage(QRectF(QPointF(tl_sx, tl_sy), QPointF(br_sx, br_sy)), f_img)

    def _draw_json_regions(self, p):
        if not hasattr(self.model, 'json_regions') or not self.model.json_regions: return
        for name, r in self.model.json_regions.items():
            tl_sx, tl_sy = self.world_to_screen(r.x(), r.y() + r.height())
            br_sx, br_sy = self.world_to_screen(r.x() + r.width(), r.y())
            rect_f = QRectF(QPointF(tl_sx, tl_sy), QPointF(br_sx, br_sy))
            p.setPen(QPen(QColor(255, 165, 0, 180), max(1, 2 if self.zoom > 5 else 1)))
            p.setBrush(Qt.NoBrush); p.drawRect(rect_f)
            if self.zoom > 2:
                font = p.font(); font.setPointSize(8); p.setFont(font)
                p.setPen(QPen(QColor(255, 200, 0, 255)))
                p.drawText(QPointF(tl_sx + 2, tl_sy + 12), name)

    def _draw_vector_points(self, p, min_x, max_x, min_y, max_y):
        if not self.model.vector_points: return
        p.setRenderHint(QPainter.Antialiasing, True); p.setBrush(QColor(255, 255, 0)); p.setPen(Qt.NoPen)
        ps = max(4, self.zoom / 3)
        for px, py in self.model.vector_points:
            sx, sy = self.world_to_screen(px, py); p.drawEllipse(QPointF(sx, sy), ps/2, ps/2)
        p.setRenderHint(QPainter.Antialiasing, False)

    def _draw_selection_rect(self, p):
        r = self.model.selection_rect; dx, dy = (self.current_move_offset if self.is_moving_pixels else (0, 0))
        tl_sx, tl_sy = self.world_to_screen(r.x() + dx, r.y() + dy + r.height())
        br_sx, br_sy = self.world_to_screen(r.x() + dx + r.width(), r.y() + dy)
        rect_f = QRectF(QPointF(tl_sx, tl_sy), QPointF(br_sx, br_sy))
        p.setPen(QPen(QColor(0, 120, 215), 2, Qt.DashLine if self.is_moving_pixels else Qt.SolidLine))
        p.setBrush(QColor(0, 120, 215, 40)); p.drawRect(rect_f)
        if not self.is_moving_pixels and self.zoom > 5:
            p.setBrush(Qt.white); p.setPen(QPen(Qt.black, 1)); size = 6
            for pt in[rect_f.topLeft(), rect_f.topRight(), rect_f.bottomLeft(), rect_f.bottomRight()]:
                p.drawRect(QRectF(pt.x()-size/2, pt.y()-size/2, size, size))

    def _draw_cursor(self, p):
        mx, my = self.mouse_world_pos; ix, iy = math.floor(mx), math.floor(my)
        sx, sy = self.world_to_screen(ix, iy + 1)
        p.setPen(QPen(QColor(255, 255, 255, 150), 1)); p.drawRect(QRectF(sx, sy, self.zoom, self.zoom))

    def check_auto_scroll(self, mouse_pos):
        margin = 30; speed = 15; dx, dy = 0, 0
        if mouse_pos.x() < margin: dx = speed
        elif mouse_pos.x() > self.width() - margin: dx = -speed
        if mouse_pos.y() < margin: dy = speed
        elif mouse_pos.y() > self.height() - margin: dy = -speed
        self.scroll_delta = (dx, dy)
        if dx != 0 or dy != 0:
            if not self.auto_scroll_timer.isActive(): self.auto_scroll_timer.start(20)
        else: self.auto_scroll_timer.stop()

    def handle_auto_scroll(self):
        self.offset_x += self.scroll_delta[0]
        self.offset_y += self.scroll_delta[1]
        current_mouse_pos = self.mapFromGlobal(QCursor.pos())
        self.last_mouse_pos = current_mouse_pos
        wx, wy = self.screen_to_world(current_mouse_pos.x(), current_mouse_pos.y())
        ix, iy, step = self._get_snapped_pos(wx, wy)
        self.mouse_world_pos = (wx, wy)
        if self.is_selecting: self._update_selection(ix, iy)
        elif self.resize_handle != RESIZE_NONE: self._perform_resize(ix, iy)
        elif self.is_moving_pixels:
            start_wx, start_wy = self.move_start_world_pos
            dx = math.floor((wx - start_wx) / step + 0.5) * step
            dy = math.floor((wy - start_wy) / step + 0.5) * step
            self.current_move_offset = (dx, dy)
        self.update()

    def wheelEvent(self, event: QWheelEvent):
        mouse_pos = event.pos()
        wx_before, wy_before = self.screen_to_world(mouse_pos.x(), mouse_pos.y())
        factor = 1.15
        if event.angleDelta().y() < 0: self.zoom = max(self.min_zoom, self.zoom / factor)
        else: self.zoom = min(self.max_zoom, self.zoom * factor)
        cx, cy = self.width() / 2, self.height() / 2
        self.offset_x = mouse_pos.x() - cx - (wx_before * self.zoom)
        self.offset_y = mouse_pos.y() - cy + (wy_before * self.zoom)
        self.update()

    def _apply_tool_line(self, x0, y0, x1, y1):
        points = get_bresenham_line(x0, y0, x1, y1)
        for px, py in points:
            if not self.model.selection_rect or self.model.selection_rect.contains(px, py):
                if self.current_tool == ToolType.PEN: self.model.set_pixel(px, py, self.current_color)
                else: self.model.erase_pixel(px, py)

    def show_context_menu(self, global_pos, grid_pos):
        menu = QMenu(self)
        is_inside = self.model.selection_rect and self.model.selection_rect.contains(grid_pos)
        m_copy = menu.addAction("复制"); m_copy.setEnabled(bool(is_inside))
        m_copy.triggered.connect(lambda: self.copy_action(grid_pos))
        m_cut = menu.addAction("剪切"); m_cut.setEnabled(bool(is_inside))
        m_cut.triggered.connect(lambda: self.cut_action(grid_pos))
        m_paste = menu.addAction("粘贴"); m_paste.setEnabled(self.model.clipboard_image is not None)
        m_paste.triggered.connect(lambda: self.paste_action(grid_pos))
        if is_inside:
            menu.addSeparator()
            menu.addAction("顺时针旋转 90°", lambda: self.rotate_action(True))
            menu.addAction("逆时针旋转 90°", lambda: self.rotate_action(False))
            menu.addSeparator()
            menu.addAction("左右翻转", lambda: self.flip_action(True))
            menu.addAction("上下翻转", lambda: self.flip_action(False))
            menu.addSeparator()
            menu.addAction("删除选区内容", self.delete_selection)
        menu.exec_(global_pos)

    def rotate_action(self, cw=True): self.model.rotate_selection_inplace(cw); self.parent().update_selection_ui(); self.update()
    def flip_action(self, h=True): self.model.flip_selection_inplace(h); self.parent().update_selection_ui(); self.update()
    def copy_action(self, pos=None):
        if pos is None and self.model.selection_rect: pos = self.model.selection_rect.topLeft()
        if pos: self.model.copy_selection(pos)
    def cut_action(self, pos=None):
        if pos is None and self.model.selection_rect: pos = self.model.selection_rect.topLeft()
        if pos: self.model.cut_selection(pos); self.update()
    def paste_action(self, pos=None):
        if pos is None:
            wx, wy = self.screen_to_world(self.width()/2, self.height()/2)
            ix, iy, _ = self._get_snapped_pos(wx, wy)
            pos = QPoint(ix, iy)
        self.model.paste_from_clipboard(pos)
        if self.model.selection_rect: self.is_moving_pixels = True 
        self.parent().update_selection_ui(); self.update()
    def delete_selection(self): self.model.delete_selection(); self.parent().update_selection_ui(); self.update()
    def get_content_rect(self): return self.model.get_content_rect()
    def get_image(self, rect): return self.model.get_image(rect)