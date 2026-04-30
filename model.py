from PyQt5.QtGui import QImage, QPainter, QColor, QTransform
from PyQt5.QtCore import QPoint, QRect, Qt
from consts import DEFAULT_WIDTH, DEFAULT_HEIGHT

class EditorModel:
    def __init__(self):
        self.main_layer = QImage(DEFAULT_WIDTH, DEFAULT_HEIGHT, QImage.Format_ARGB32_Premultiplied)
        self.main_layer.fill(Qt.transparent)
        
        self.layer_origin = QPoint(0, 0)
        self.vector_points = set()
        
        self.selection_rect = None 
        self.floating_layer = None 
        
        self.clipboard_image = None
        self.clipboard_anchor_offset = QPoint(0, 0) 
        
        self.undo_stack =[]
        self.redo_stack =[]
        self.max_history = 30
        
        self.json_regions = {}

    def push_undo_state(self):
        if len(self.undo_stack) >= self.max_history: self.undo_stack.pop(0)
        self.undo_stack.append(self._create_state_snapshot())
        self.redo_stack.clear()

    def undo(self):
        if not self.undo_stack: return
        self._save_current_to_redo()
        self._restore_state(self.undo_stack.pop())

    def redo(self):
        if not self.redo_stack: return
        self._save_current_to_undo()
        self._restore_state(self.redo_stack.pop())

    def _save_current_to_redo(self): self.redo_stack.append(self._create_state_snapshot())
    def _save_current_to_undo(self): self.undo_stack.append(self._create_state_snapshot())

    def _create_state_snapshot(self):
        return {
            'image': self.main_layer.copy(),
            'origin': QPoint(self.layer_origin),
            'selection': QRect(self.selection_rect) if self.selection_rect else None,
            'points': self.vector_points.copy(),
            'floating': self.floating_layer.copy() if self.floating_layer else None
        }

    def _restore_state(self, state):
        self.main_layer = state['image']
        self.layer_origin = state['origin']
        self.selection_rect = state['selection']
        self.vector_points = state['points']
        self.floating_layer = state['floating']

    def ensure_canvas_covers(self, x, y):
        ox, oy = self.layer_origin.x(), self.layer_origin.y()
        w, h = self.main_layer.width(), self.main_layer.height()
        rel_x = x - ox; rel_y = oy + h - 1 - y 
        if 0 <= rel_x < w and 0 <= rel_y < h: return 
        new_ox = min(ox, x); new_max_x = max(ox + w, x + 1)
        new_oy = min(oy, y); new_max_y = max(oy + h, y + 1)
        new_w = max(new_max_x - new_ox, int(w * 1.2)); new_h = max(new_max_y - new_oy, int(h * 1.2))
        new_ox = min(new_ox, ox); new_oy = min(new_oy, oy)
        new_img = QImage(new_w, new_h, QImage.Format_ARGB32_Premultiplied)
        new_img.fill(Qt.transparent)
        offset_x = ox - new_ox; offset_y = (new_oy + new_h) - (oy + h)
        p = QPainter(new_img); p.drawImage(offset_x, offset_y, self.main_layer); p.end()
        self.main_layer = new_img; self.layer_origin = QPoint(new_ox, new_oy)

    def set_pixel(self, x, y, color):
        self.ensure_canvas_covers(x, y)
        ox, oy = self.layer_origin.x(), self.layer_origin.y()
        h = self.main_layer.height()
        self.main_layer.setPixelColor(x - ox, oy + h - 1 - y, color)

    def erase_pixel(self, x, y): self.set_pixel(x, y, QColor(0,0,0,0))
    
    def clear_canvas(self):
        self.push_undo_state()
        self.main_layer.fill(Qt.transparent)
        self.selection_rect = None
        self.vector_points.clear()
        self.floating_layer = None
        self.json_regions.clear()

    def is_canvas_empty(self):
        if len(self.undo_stack) > 0: return False
        return True

    def load_image(self, img):
        self.push_undo_state()
        self.main_layer = img.copy()
        w, h = img.width(), img.height()
        self.layer_origin = QPoint(0, 0)
        self.selection_rect = QRect(0, 0, w, h)
        self.vector_points.clear()
        self.floating_layer = None
        self.json_regions.clear()

    def append_image_right(self, img):
        self.push_undo_state()
        current_w = self.main_layer.width()
        current_h = self.main_layer.height()
        ox, oy = self.layer_origin.x(), self.layer_origin.y()
        start_x = ox + current_w 
        start_y = oy
        new_img_w = img.width()
        new_img_h = img.height()
        self.ensure_canvas_covers(start_x + new_img_w, start_y + new_img_h)
        nox, noy = self.layer_origin.x(), self.layer_origin.y()
        nmh = self.main_layer.height()
        dest_x = start_x - nox
        dest_y = noy + nmh - (start_y + new_img_h)
        p = QPainter(self.main_layer)
        p.drawImage(dest_x, dest_y, img)
        p.end()
        self.selection_rect = QRect(start_x, start_y, new_img_w, new_img_h)

    def load_json_regions(self, regions_dict):
        self.json_regions = {}
        ox, oy = self.layer_origin.x(), self.layer_origin.y()
        mh = self.main_layer.height()
        for name, r in regions_dict.items():
            if isinstance(r, dict) and all(k in r for k in ('x', 'y', 'w', 'h')):
                wx = ox + r['x']
                wy = oy + mh - r['y'] - r['h']
                self.json_regions[name] = QRect(wx, wy, r['w'], r['h'])

    def rotate_selection_inplace(self, clockwise=True):
        if not self.selection_rect: return
        self.push_undo_state()
        rect = self.selection_rect
        sub_img = self.get_image(rect)
        if sub_img.isNull(): return
        ox, oy = self.layer_origin.x(), self.layer_origin.y()
        mh = self.main_layer.height()
        p = QPainter(self.main_layer)
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.fillRect(rect.x()-ox, oy+mh-(rect.y()+rect.height()), rect.width(), rect.height(), Qt.transparent)
        p.end()
        transform = QTransform().rotate(90 if clockwise else -90)
        rotated_img = sub_img.transformed(transform, Qt.SmoothTransformation)
        new_w, new_h = rotated_img.width(), rotated_img.height()
        new_rect = QRect(rect.x(), rect.y(), new_w, new_h)
        self.selection_rect = new_rect
        self.ensure_canvas_covers(new_rect.x(), new_rect.y())
        self.ensure_canvas_covers(new_rect.x() + new_w, new_rect.y() + new_h)
        ox, oy = self.layer_origin.x(), self.layer_origin.y()
        mh = self.main_layer.height()
        p2 = QPainter(self.main_layer)
        p2.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p2.drawImage(new_rect.x()-ox, oy+mh-(new_rect.y()+new_h), rotated_img)
        p2.end()
        self.floating_layer = None

    # --- 新增功能: 翻转 ---
    def flip_selection_inplace(self, horizontal=True):
        if not self.selection_rect: return
        self.push_undo_state()
        rect = self.selection_rect
        sub_img = self.get_image(rect)
        if sub_img.isNull(): return
        
        ox, oy = self.layer_origin.x(), self.layer_origin.y()
        mh = self.main_layer.height()
        
        # 清除原图
        p = QPainter(self.main_layer)
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.fillRect(rect.x()-ox, oy+mh-(rect.y()+rect.height()), rect.width(), rect.height(), Qt.transparent)
        p.end()
        
        # 翻转
        flipped_img = sub_img.mirrored(horizontal, not horizontal)
        
        # 贴回
        p2 = QPainter(self.main_layer)
        p2.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p2.drawImage(rect.x()-ox, oy+mh-(rect.y()+rect.height()), flipped_img)
        p2.end()
        self.floating_layer = None

    def lift_selection(self):
        if not self.selection_rect: return
        r = self.selection_rect
        w, h = r.width(), r.height()
        self.floating_layer = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        self.floating_layer.fill(Qt.transparent)
        ox, oy = self.layer_origin.x(), self.layer_origin.y()
        mh = self.main_layer.height()
        src_x = r.x() - ox
        src_y = oy + mh - (r.y() + h)
        p = QPainter(self.floating_layer)
        p.drawImage(0, 0, self.main_layer, src_x, src_y, w, h)
        p.end()
        p_main = QPainter(self.main_layer)
        p_main.setCompositionMode(QPainter.CompositionMode_Clear)
        p_main.fillRect(src_x, src_y, w, h, Qt.transparent)
        p_main.end()

    def drop_selection(self, dx, dy):
        if not self.floating_layer or not self.selection_rect: 
            self.floating_layer = None
            return
        new_x = self.selection_rect.x() + dx
        new_y = self.selection_rect.y() + dy
        w, h = self.floating_layer.width(), self.floating_layer.height()
        self.ensure_canvas_covers(new_x, new_y)
        self.ensure_canvas_covers(new_x + w, new_y + h)
        ox, oy = self.layer_origin.x(), self.layer_origin.y()
        mh = self.main_layer.height()
        dest_x = new_x - ox
        dest_y = oy + mh - (new_y + h)
        p = QPainter(self.main_layer)
        p.drawImage(dest_x, dest_y, self.floating_layer)
        p.end()
        self.selection_rect.translate(dx, dy)
        self.floating_layer = None

    def delete_selection(self):
        if self.floating_layer: 
            self.push_undo_state()
            self.floating_layer = None
            return 
        if self.selection_rect:
            self.push_undo_state()
            r = self.selection_rect
            ox, oy = self.layer_origin.x(), self.layer_origin.y()
            mh = self.main_layer.height()
            src_x = r.x() - ox
            src_y = oy + mh - (r.y() + r.height())
            p = QPainter(self.main_layer)
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.fillRect(src_x, src_y, r.width(), r.height(), Qt.transparent)
            p.end()

    def copy_selection(self, anchor_grid_pos):
        if not self.selection_rect: return
        self.clipboard_anchor_offset = anchor_grid_pos - self.selection_rect.topLeft()
        r = self.selection_rect
        img = self.get_image(r)
        self.clipboard_image = img

    def cut_selection(self, anchor_grid_pos):
        if not self.selection_rect: return
        self.copy_selection(anchor_grid_pos)
        self.delete_selection()

    def paste_from_clipboard(self, target_grid_pos):
        if not self.clipboard_image: return
        self.push_undo_state()
        top_left = target_grid_pos - self.clipboard_anchor_offset
        w, h = self.clipboard_image.width(), self.clipboard_image.height()
        self.floating_layer = self.clipboard_image.copy()
        self.selection_rect = QRect(top_left.x(), top_left.y(), w, h)
        self.ensure_canvas_covers(top_left.x(), top_left.y())
        self.ensure_canvas_covers(top_left.x() + w, top_left.y() + h)

    def get_content_rect(self):
        ox, oy = self.layer_origin.x(), self.layer_origin.y()
        w, h = self.main_layer.width(), self.main_layer.height()
        return QRect(ox, oy, w, h)

    def get_image(self, rect):
        if not rect or rect.isEmpty(): return QImage()
        w, h = rect.width(), rect.height()
        ox, oy = self.layer_origin.x(), self.layer_origin.y()
        mh = self.main_layer.height()
        src_x = rect.x() - ox
        src_y = oy + mh - (rect.y() + h)
        return self.main_layer.copy(src_x, src_y, w, h)