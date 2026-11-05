import math
from PyQt5.QtWidgets import QWidget, QMenu
from PyQt5.QtGui import QPainter, QPen, QColor, QMouseEvent, QWheelEvent, QCursor
from PyQt5.QtCore import Qt, QPointF, QRectF, QPoint, QRect, QTimer

from consts import ToolType, DEFAULT_COLOR, BACKGROUND_COLOR
from utils import get_grid_pos, get_intersection_pos, get_bresenham_line
from model import EditorModel
from dialogs import ColorOverlayDialog, ScaleSelectionDialog

RESIZE_NONE = 0
RESIZE_LEFT = 1
RESIZE_RIGHT = 2
RESIZE_TOP = 4      
RESIZE_BOTTOM = 8

# At high zoom, drawing an entire QImage into one scaled QRect can distribute
# fractional target pixels differently from the grid's per-line rounding.  Once
# individual texels are large enough, render only the visible texels with the
# exact same rounded world edges used by the grid.
PIXEL_ALIGNED_RENDER_ZOOM = 12.0


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
        # None until the pointer actually enters the canvas.  This prevents a
        # phantom hover cell (and its coordinate labels) at the origin during
        # application startup.
        self.mouse_world_pos = None
        self.selected_pixel_world = None
        
        self.is_selecting = False
        self.selection_start_grid = None
        self.interaction_snap_step = None
        
        self.is_moving_pixels = False
        self.move_start_world_pos = (0, 0)
        self.current_move_offset = (0, 0)
        self.moving_json_region_names = set()
        
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

    @staticmethod
    def _round_device(value):
        """Round a logical screen coordinate consistently on both axes.

        Python's built-in round uses bankers' rounding at exactly .5, which can
        make adjacent grid edges choose different sides.  Pixel boundaries and
        grid lines must use one deterministic half-away-from-zero rule.
        """
        if value >= 0:
            return int(math.floor(value + 0.5))
        return int(math.ceil(value - 0.5))

    def _screen_x_edge(self, world_x):
        sx, _ = self.world_to_screen(world_x, 0)
        return self._round_device(sx)

    def _screen_y_edge(self, world_y):
        _, sy = self.world_to_screen(0, world_y)
        return self._round_device(sy)

    def _world_pixel_screen_rect(self, world_x, world_y):
        """Return the integer device rectangle for one world-space texel."""
        left = self._screen_x_edge(world_x)
        right = self._screen_x_edge(world_x + 1)
        top = self._screen_y_edge(world_y + 1)
        bottom = self._screen_y_edge(world_y)
        return QRect(left, top, max(1, right - left), max(1, bottom - top))

    def get_visible_pixel_color(self, world_x, world_y):
        """Return the pixel data currently shown at a world-space texel."""
        if self.is_moving_pixels and self.model.floating_layer:
            dx, dy = self.current_move_offset
            moved_rect = QRect(self.model.selection_rect)
            moved_rect.translate(dx, dy)
            if moved_rect.contains(world_x, world_y):
                image_x = world_x - moved_rect.x()
                image_y = moved_rect.y() + moved_rect.height() - 1 - world_y
                return self.model.floating_layer.pixelColor(image_x, image_y)
        return self.model.get_pixel_color(world_x, world_y)

    def select_pixel(self, world_x, world_y):
        self.selected_pixel_world = (int(world_x), int(world_y))
        self.refresh_selected_pixel_ui()

    def refresh_selected_pixel_ui(self):
        if not self.parent() or not hasattr(self.parent(), 'update_selected_region_ui'):
            return

        selection = self.model.selection_rect
        if (
            self.current_tool == ToolType.SELECT
            and selection
            and not selection.isEmpty()
        ):
            selection = QRect(selection)
            color = None
            if selection.width() == 1 and selection.height() == 1:
                color = self.get_visible_pixel_color(selection.x(), selection.y())
            self.parent().update_selected_region_ui(selection, color)
            return

        if self.selected_pixel_world is None:
            self.parent().update_selected_region_ui(None, None)
            return
        world_x, world_y = self.selected_pixel_world
        color = self.get_visible_pixel_color(world_x, world_y)
        self.parent().update_selected_pixel_ui(world_x, world_y, color)

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
                self.interaction_snap_step = step
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
                    if self.parent() and hasattr(self.parent(), 'update_selection_ui'):
                        self.parent().update_selection_ui()
                self.model.push_undo_state()
                self._apply_tool_line(pix_x, pix_y, pix_x, pix_y)
                self.last_grid_pos = (pix_x, pix_y)
            elif self.current_tool == ToolType.SELECT:
                pix_x, pix_y = get_grid_pos(wx, wy)
                if self.model.selection_rect and self.model.selection_rect.contains(pix_x, pix_y):
                    sync_json_regions = bool(
                        event.modifiers() & Qt.ControlModifier
                    )
                    if not self._start_json_region_move_sync(sync_json_regions):
                        if self.parent() and hasattr(self.parent(), 'statusBar'):
                            self.parent().statusBar().showMessage(
                                "无法移动：选区只包含了部分 JSON 切片",
                                3000,
                            )
                        self.setCursor(Qt.ForbiddenCursor)
                        self.update()
                        return
                    if not self.is_moving_pixels:
                        self.model.push_undo_state()
                        self.is_moving_pixels = True
                        self.model.lift_selection()
                    self.move_start_world_pos = (wx, wy)
                    self.current_move_offset = (0, 0)
                    self.interaction_snap_step = step
                else:
                    if self.is_moving_pixels:
                        self.model.drop_selection(0, 0)
                        self.is_moving_pixels = False
                        self.moving_json_region_names.clear()
                    self.is_selecting = True
                    self.selection_start_grid = (ix, iy)
                    self.interaction_snap_step = step
                    self.model.selection_rect = QRect(ix, iy, step, step)
                    if self.parent() and hasattr(self.parent(), 'update_selection_ui'):
                        self.parent().update_selection_ui()
            selected_x, selected_y = get_grid_pos(wx, wy)
            self.select_pixel(selected_x, selected_y)
            self.update()
        elif event.button() == Qt.RightButton:
            grid_x, grid_y = get_grid_pos(wx, wy)
            self.select_pixel(grid_x, grid_y)
            self.show_context_menu(event.globalPos(), QPoint(grid_x, grid_y))
        elif event.button() == Qt.MiddleButton:
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent):
        wx, wy = self.screen_to_world(event.x(), event.y())
        ix, iy, step = self._get_snapped_pos(wx, wy)
        self.mouse_world_pos = (wx, wy)
        
        if self.parent() and hasattr(self.parent(), 'update_mouse_status'):
            hover_x, hover_y = get_grid_pos(wx, wy)
            self.parent().update_mouse_status(
                hover_x, hover_y, self.zoom, hovering=True
            )
            
        delta = event.pos() - self.last_mouse_pos
        
        if (event.buttons() & Qt.MiddleButton) or \
           (event.buttons() & Qt.RightButton and self.current_tool != ToolType.POINT and not self.model.selection_rect):
            self.offset_x += delta.x()
            self.offset_y += delta.y()
            
        if event.buttons() & Qt.LeftButton:
            if self.resize_handle != RESIZE_NONE:
                self._perform_resize(wx, wy)
                self.check_auto_scroll(event.pos())
            elif self.is_moving_pixels:
                start_wx, start_wy = self.move_start_world_pos
                step = self.interaction_snap_step or step
                dx = math.floor((wx - start_wx) / step + 0.5) * step
                dy = math.floor((wy - start_wy) / step + 0.5) * step
                self.current_move_offset = (dx, dy)
                self.check_auto_scroll(event.pos())
            elif self.is_selecting:
                step = self.interaction_snap_step or step
                ix = math.floor(wx / step) * step
                iy = math.floor(wy / step) * step
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

    def leaveEvent(self, event):
        """Hide the hovered-cell annotation when the pointer leaves the canvas."""
        self.mouse_world_pos = None
        if self.parent() and hasattr(self.parent(), 'update_mouse_status'):
            self.parent().update_mouse_status(None, None, self.zoom, hovering=False)
        self.update()
        super().leaveEvent(event)

    def _perform_resize(self, wx, wy):
        if not self.resize_start_rect: return
        rect = self.resize_start_rect
        l, r = rect.x(), rect.x() + rect.width()
        b, t = rect.y(), rect.y() + rect.height()
        step = self.interaction_snap_step or self.get_snap_step()
        edge_x = round(wx / step) * step
        edge_y = round(wy / step) * step

        if self.resize_handle & RESIZE_LEFT: l = edge_x
        if self.resize_handle & RESIZE_RIGHT: r = edge_x
        if self.resize_handle & RESIZE_BOTTOM: b = edge_y
        if self.resize_handle & RESIZE_TOP: t = edge_y
        
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
            self.selection_start_grid = None
            if self.is_moving_pixels:
                dx, dy = self.current_move_offset
                self.is_moving_pixels = False
                self.model.drop_selection(dx, dy)
                self._commit_json_region_move_sync(dx, dy)
                self.current_move_offset = (0, 0)
                if self.parent() and hasattr(self.parent(), 'update_selection_ui'):
                    self.parent().update_selection_ui()
            self.interaction_snap_step = None
            self.refresh_selected_pixel_ui()
        self.setCursor(Qt.ArrowCursor)
        self.update()

    def _start_json_region_move_sync(self, enabled):
        self.moving_json_region_names.clear()
        selection = self.model.selection_rect
        if not enabled or not selection:
            return True

        intersecting_regions = {
            name
            for name, rect in self.model.json_regions.items()
            if selection.intersects(rect)
        }
        if any(
            not selection.contains(self.model.json_regions[name])
            for name in intersecting_regions
        ):
            return False

        self.moving_json_region_names = intersecting_regions
        return True

    def _commit_json_region_move_sync(self, dx, dy):
        moved_names = set(self.moving_json_region_names)
        self.moving_json_region_names.clear()
        if not moved_names or (dx == 0 and dy == 0):
            return
        for name in moved_names:
            rect = self.model.json_regions.get(name)
            if rect is not None:
                rect.translate(dx, dy)
        if self.parent() and hasattr(self.parent(), 'refresh_region_list'):
            self.parent().refresh_region_list()

    def _update_selection(self, ix, iy):
        if self.selection_start_grid is None: return
        sx, sy = self.selection_start_grid
        step = self.interaction_snap_step or self.get_snap_step()
        x1, x2 = min(sx, ix), max(sx, ix)
        y1, y2 = min(sy, iy), max(sy, iy)
        self.model.selection_rect = QRect(
            x1, y1, x2 - x1 + step, y2 - y1 + step
        )
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
        # The internal grid is always Y-up. Labels are converted through the
        # active coordinate convention, so TOP_LEFT mode visibly counts down.
        if self.zoom > 5:
            p.setPen(QPen(QColor(50, 50, 50), 1))
            for x in range(math.floor(min_x), math.ceil(max_x) + 1):
                sx, _ = self.world_to_screen(x, 0)
                p.drawLine(self._round_device(sx), 0, self._round_device(sx), self.height())
            for y in range(math.floor(min_y), math.ceil(max_y) + 1):
                _, sy = self.world_to_screen(0, y)
                p.drawLine(0, self._round_device(sy), self.width(), self._round_device(sy))

        step = 8
        while (step * self.zoom) < 64:
            step *= 2

        _, axis_y = self.world_to_screen(0, 0)
        axis_x, _ = self.world_to_screen(0, 0)
        label_y = min(max(int(axis_y) + 14, 14), self.height() - 4)
        label_x = min(max(int(axis_x) + 4, 4), self.width() - 50)

        font = p.font()
        font.setPointSize(8)
        p.setFont(font)

        for x in range(math.floor(min_x / step) * step,
                       math.ceil(max_x / step) * step + 1, step):
            sx, _ = self.world_to_screen(x, 0)
            is_axis = x == 0
            p.setPen(QPen(QColor(200, 200, 200), 2) if is_axis else QPen(QColor(90, 90, 90), 1))
            p.drawLine(self._round_device(sx), 0, self._round_device(sx), self.height())
            if self.zoom * step >= 48 and 0 <= sx <= self.width():
                display_x, _ = self.model.world_to_display(x, 0)
                p.setPen(QPen(QColor(165, 165, 165), 1))
                p.drawText(int(sx) + 3, label_y, str(int(display_x)))

        for y in range(math.floor(min_y / step) * step,
                       math.ceil(max_y / step) * step + 1, step):
            _, sy = self.world_to_screen(0, y)
            is_axis = y == 0
            p.setPen(QPen(QColor(200, 200, 200), 2) if is_axis else QPen(QColor(90, 90, 90), 1))
            p.drawLine(0, self._round_device(sy), self.width(), self._round_device(sy))
            if self.zoom * step >= 48 and 0 <= sy <= self.height():
                _, display_y = self.model.world_to_display(0, y)
                p.setPen(QPen(QColor(165, 165, 165), 1))
                p.drawText(label_x, int(sy) - 3, str(int(display_y)))

    def _draw_world_image(self, p, image, world_x, world_y):
        """Draw an image whose lower-left world edge is ``(world_x, world_y)``.

        For normal zoom levels a single nearest-neighbour image draw is faster.
        At high zoom, visible texels are painted one by one using the same
        rounded screen edges as the coordinate grid.  This avoids the
        scale-dependent one-pixel drift produced by two independent rounding
        paths in Qt's image scaler and our grid renderer.
        """
        if image is None or image.isNull():
            return

        width, height = image.width(), image.height()
        if self.zoom < PIXEL_ALIGNED_RENDER_ZOOM:
            p.setRenderHint(QPainter.SmoothPixmapTransform, False)
            tl_sx, tl_sy = self.world_to_screen(world_x, world_y + height)
            br_sx, br_sy = self.world_to_screen(world_x + width, world_y)
            p.drawImage(
                QRectF(QPointF(tl_sx, tl_sy), QPointF(br_sx, br_sy)), image
            )
            return

        # Clip the Python loop to the texels currently visible in the widget.
        left_w, top_w = self.screen_to_world(0, 0)
        right_w, bottom_w = self.screen_to_world(self.width(), self.height())
        visible_left = math.floor(min(left_w, right_w)) - 1
        visible_right = math.ceil(max(left_w, right_w)) + 1
        visible_bottom = math.floor(min(bottom_w, top_w)) - 1
        visible_top = math.ceil(max(bottom_w, top_w)) + 1

        start_x = max(world_x, visible_left)
        end_x = min(world_x + width, visible_right)
        start_y = max(world_y, visible_bottom)
        end_y = min(world_y + height, visible_top)
        if start_x >= end_x or start_y >= end_y:
            return

        for wy in range(start_y, end_y):
            source_y = world_y + height - 1 - wy
            for wx in range(start_x, end_x):
                color = image.pixelColor(wx - world_x, source_y)
                if color.alpha() == 0:
                    continue
                p.fillRect(self._world_pixel_screen_rect(wx, wy), color)

    def _draw_main_layer(self, p):
        origin = self.model.layer_origin
        self._draw_world_image(
            p, self.model.main_layer, origin.x(), origin.y()
        )

    def _draw_floating_layer(self, p):
        if self.is_moving_pixels and self.model.floating_layer:
            dx, dy = self.current_move_offset
            rect = self.model.selection_rect
            self._draw_world_image(
                p,
                self.model.floating_layer,
                rect.x() + dx,
                rect.y() + dy,
            )

    def _draw_json_regions(self, p):
        if not hasattr(self.model, 'json_regions') or not self.model.json_regions: return
        for name, r in self.model.json_regions.items():
            if self.is_moving_pixels and name in self.moving_json_region_names:
                r = QRect(r)
                r.translate(*self.current_move_offset)
            tl_sx, tl_sy = self.world_to_screen(r.x(), r.y() + r.height())
            br_sx, br_sy = self.world_to_screen(r.x() + r.width(), r.y())
            rect_f = QRectF(QPointF(tl_sx, tl_sy), QPointF(br_sx, br_sy))
            p.setPen(QPen(QColor(255, 165, 0, 180), max(1, 2 if self.zoom > 5 else 1)))
            p.setBrush(Qt.NoBrush); p.drawRect(rect_f)
            if self.zoom > 2:
                font = p.font(); font.setPointSize(8); p.setFont(font)
                p.setPen(QPen(QColor(255, 200, 0, 255)))
                p.drawText(QPointF(tl_sx + 2, tl_sy + 12), name)
                center_offset = self.model.json_region_centers.get(
                    name, QPointF(0, 0)
                )
                center_x = r.x() + r.width() / 2.0 + center_offset.x()
                center_y = r.y() + r.height() / 2.0 + center_offset.y()
                center_sx, center_sy = self.world_to_screen(center_x, center_y)
                p.setRenderHint(QPainter.Antialiasing, True)
                p.setPen(QPen(QColor(25, 25, 25, 230), 1))
                p.setBrush(QColor(255, 200, 0, 245))
                p.drawEllipse(QPointF(center_sx, center_sy), 4, 4)
                p.setRenderHint(QPainter.Antialiasing, False)

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
        """Outline the hovered pixel; its corner coordinates live in the dock."""
        if self.mouse_world_pos is None:
            return

        mx, my = self.mouse_world_pos
        ix, iy = math.floor(mx), math.floor(my)
        rect = self._world_pixel_screen_rect(ix, iy)
        p.setPen(QPen(QColor(255, 255, 255, 150), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(rect)

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
        if self.is_selecting:
            step = self.interaction_snap_step or step
            ix = math.floor(wx / step) * step
            iy = math.floor(wy / step) * step
            self._update_selection(ix, iy)
        elif self.resize_handle != RESIZE_NONE: self._perform_resize(wx, wy)
        elif self.is_moving_pixels:
            start_wx, start_wy = self.move_start_world_pos
            step = self.interaction_snap_step or step
            dx = math.floor((wx - start_wx) / step + 0.5) * step
            dy = math.floor((wy - start_wy) / step + 0.5) * step
            self.current_move_offset = (dx, dy)
        selected_x, selected_y = get_grid_pos(wx, wy)
        if self.parent() and hasattr(self.parent(), 'update_mouse_status'):
            self.parent().update_mouse_status(
                selected_x, selected_y, self.zoom, hovering=True
            )
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
            menu.addAction("缩放…", self.scale_selection_action)
            menu.addAction("叠加颜色…", self.overlay_color_action)
            menu.addSeparator()
            menu.addAction("删除选区内容", self.delete_selection)
        menu.exec_(global_pos)

    def _commit_floating_selection(self):
        if not self.is_moving_pixels:
            return
        dx, dy = self.current_move_offset
        self.model.drop_selection(dx, dy)
        self._commit_json_region_move_sync(dx, dy)
        self.is_moving_pixels = False
        self.current_move_offset = (0, 0)

    def rotate_action(self, cw=True):
        self._commit_floating_selection()
        self.model.rotate_selection_inplace(cw)
        if self.parent() and hasattr(self.parent(), 'update_selection_ui'):
            self.parent().update_selection_ui()
        self.update()

    def flip_action(self, h=True):
        self._commit_floating_selection()
        self.model.flip_selection_inplace(h)
        if self.parent() and hasattr(self.parent(), 'update_selection_ui'):
            self.parent().update_selection_ui()
        self.update()

    def scale_selection_action(self):
        if not self.model.selection_rect:
            return
        self._commit_floating_selection()

        rect = self.model.selection_rect
        dialog = ScaleSelectionDialog(rect.width(), rect.height(), self)
        if not dialog.exec_():
            return

        scale_x, scale_y = dialog.scale_factors()
        target_width, target_height = dialog.target_size()
        try:
            changed = self.model.scale_selection_inplace(
                scale_x,
                scale_y,
                dialog.sampling_mode(),
                dialog.scale_center(),
                target_width,
                target_height,
            )
        except ValueError as error:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "无法缩放选区", str(error))
            return
        if changed:
            self.parent().update_selection_ui()
            self.update()

    def overlay_color_action(self):
        if not self.model.selection_rect:
            return
        self._commit_floating_selection()

        source = self.model.get_image(self.model.selection_rect)
        if source.isNull():
            return
        dialog = ColorOverlayDialog(source, self.current_color, self)
        if not dialog.exec_():
            return
        if self.model.overlay_selection_color(
            dialog.selected_color(), dialog.blend_mode()
        ):
            self.refresh_selected_pixel_ui()
            if self.parent() and hasattr(self.parent(), 'update_selection_ui'):
                self.parent().update_selection_ui()
            self.update()

    def copy_action(self, pos=None):
        if self.model.selection_rect:
            # World-space Y points upward, so QRect(x, y, ...) starts at the
            # visually lower-left corner. Always use that corner as the copy
            # anchor; right-click position must not change later paste offsets.
            anchor = QPoint(
                self.model.selection_rect.x(), self.model.selection_rect.y()
            )
            self.model.copy_selection(anchor)
    def cut_action(self, pos=None):
        if self.model.selection_rect:
            anchor = QPoint(
                self.model.selection_rect.x(), self.model.selection_rect.y()
            )
            self.model.cut_selection(anchor)
            self.update()
    def paste_action(self, pos=None):
        if pos is None:
            if self.model.selection_rect:
                # Paste the copied image's lower-left corner onto the current
                # (new) selection's lower-left corner.
                pos = QPoint(
                    self.model.selection_rect.x(),
                    self.model.selection_rect.y(),
                )
            else:
                wx, wy = self.screen_to_world(self.width()/2, self.height()/2)
                ix, iy, _ = self._get_snapped_pos(wx, wy)
                pos = QPoint(ix, iy)
        self.model.paste_from_clipboard(pos)
        if self.model.selection_rect: self.is_moving_pixels = True 
        self.parent().update_selection_ui(); self.update()
    def delete_selection(self): self.model.delete_selection(); self.parent().update_selection_ui(); self.update()
    def get_content_rect(self): return self.model.get_content_rect()
    def get_image(self, rect): return self.model.get_image(rect)
