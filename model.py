import math

from PyQt5.QtGui import QImage, QPainter, QColor, QTransform
from PyQt5.QtCore import QPoint, QPointF, QRect, Qt

from consts import DEFAULT_WIDTH, DEFAULT_HEIGHT, CoordinateMode
from utils import blend_color_image


class EditorModel:
    """Pixel data is stored in an internal Y-up world coordinate system.

    CoordinateMode only changes the coordinates shown to users and written to
    JSON. In TOP_LEFT_Y_DOWN mode, display_y == -world_y; in
    BOTTOM_LEFT_Y_UP mode, display_y == world_y.
    """

    def __init__(self):
        self.coordinate_mode = CoordinateMode.TOP_LEFT_Y_DOWN
        self.main_layer = self._new_empty_image(DEFAULT_WIDTH, DEFAULT_HEIGHT)
        self.layer_origin = self._default_origin(DEFAULT_HEIGHT)

        self.vector_points = set()
        self.selection_rect = None
        self.floating_layer = None

        self.clipboard_image = None
        self.clipboard_anchor_offset = QPoint(0, 0)

        self.undo_stack = []
        self.redo_stack = []
        self.max_history = 30

        self.json_regions = {}
        self.json_region_centers = {}
        self.json_region_scales = {}
        self.json_region_mipmaps = {}
        self.imported_bounds = None
        self.document_initialized = False

    @staticmethod
    def _new_empty_image(width, height):
        image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        return image

    def _default_origin(self, height):
        return QPoint(0, -height if self.coordinate_mode.y_down else 0)

    def canvas_rect(self):
        return QRect(
            self.layer_origin.x(),
            self.layer_origin.y(),
            self.main_layer.width(),
            self.main_layer.height(),
        )

    # ------------------------------------------------------------------
    # Coordinate convention
    # ------------------------------------------------------------------
    def world_to_display(self, x, y):
        return x, (-y if self.coordinate_mode.y_down else y)

    def display_to_world(self, x, y):
        return x, (-y if self.coordinate_mode.y_down else y)

    def world_pixel_to_display(self, x, y):
        """Convert an integer world texel coordinate to the displayed pixel index."""
        if self.coordinate_mode.y_down:
            return x, -(y + 1)
        return x, y

    def world_rect_to_display_edges(self, rect):
        """Return left, top, right, bottom in the active display convention."""
        left = rect.x()
        right = rect.x() + rect.width()
        world_bottom = rect.y()
        world_top = rect.y() + rect.height()
        if self.coordinate_mode.y_down:
            top = -world_top
            bottom = -world_bottom
        else:
            top = world_top
            bottom = world_bottom
        return left, top, right, bottom

    def display_edges_to_world_rect(self, left, top, right, bottom):
        wx1, wy1 = self.display_to_world(left, top)
        wx2, wy2 = self.display_to_world(right, bottom)
        x = min(wx1, wx2)
        y = min(wy1, wy2)
        return QRect(x, y, max(1, abs(wx2 - wx1)), max(1, abs(wy2 - wy1)))

    def set_coordinate_mode(self, mode, reanchor=True):
        if not isinstance(mode, CoordinateMode):
            mode = CoordinateMode(mode)
        if mode is self.coordinate_mode:
            return False

        self.coordinate_mode = mode
        if reanchor and self.document_initialized:
            rect = self.canvas_rect()
            dx = -rect.x()
            if mode.y_down:
                dy = -(rect.y() + rect.height())  # texture top -> world Y=0
            else:
                dy = -rect.y()  # texture bottom -> world Y=0
            self._translate_document(dx, dy)
        elif not self.document_initialized:
            self.layer_origin = self._default_origin(self.main_layer.height())

        # History snapshots contain world-space rectangles. Reanchor them too,
        # otherwise Undo after changing the convention would restore data in
        # the old coordinate frame.
        self._reanchor_history(self.undo_stack, mode)
        self._reanchor_history(self.redo_stack, mode)
        return True

    @staticmethod
    def _reanchor_history(stack, mode):
        for state in stack:
            image = state["image"]
            origin = state["origin"]
            initialized = state.get("document_initialized", True)
            if initialized:
                dx = -origin.x()
                dy = -(origin.y() + image.height()) if mode.y_down else -origin.y()
            else:
                dx = -origin.x()
                target_y = -image.height() if mode.y_down else 0
                dy = target_y - origin.y()

            if dx == 0 and dy == 0:
                continue
            state["origin"] = QPoint(origin.x() + dx, origin.y() + dy)
            if state.get("selection"):
                state["selection"].translate(dx, dy)
            if state.get("imported_bounds"):
                state["imported_bounds"].translate(dx, dy)
            state["points"] = {(x + dx, y + dy) for x, y in state["points"]}
            state["json_regions"] = {
                name: QRect(rect).translated(dx, dy)
                for name, rect in state.get("json_regions", {}).items()
            }

    def _translate_document(self, dx, dy):
        if dx == 0 and dy == 0:
            return
        self.layer_origin += QPoint(dx, dy)
        if self.selection_rect:
            self.selection_rect.translate(dx, dy)
        if self.imported_bounds:
            self.imported_bounds.translate(dx, dy)
        if self.json_regions:
            self.json_regions = {
                name: QRect(rect).translated(dx, dy)
                for name, rect in self.json_regions.items()
            }
        self.vector_points = {(x + dx, y + dy) for x, y in self.vector_points}

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------
    def push_undo_state(self):
        if len(self.undo_stack) >= self.max_history:
            self.undo_stack.pop(0)
        self.undo_stack.append(self._create_state_snapshot())
        self.redo_stack.clear()

    def undo(self):
        if not self.undo_stack:
            return False
        self._save_current_to_redo()
        self._restore_state(self.undo_stack.pop())
        return True

    def redo(self):
        if not self.redo_stack:
            return False
        self._save_current_to_undo()
        self._restore_state(self.redo_stack.pop())
        return True

    def _save_current_to_redo(self):
        self.redo_stack.append(self._create_state_snapshot())

    def _save_current_to_undo(self):
        if len(self.undo_stack) >= self.max_history:
            self.undo_stack.pop(0)
        self.undo_stack.append(self._create_state_snapshot())

    def _create_state_snapshot(self):
        return {
            "image": self.main_layer.copy(),
            "origin": QPoint(self.layer_origin),
            "selection": QRect(self.selection_rect) if self.selection_rect else None,
            "points": self.vector_points.copy(),
            "floating": self.floating_layer.copy() if self.floating_layer else None,
            "json_regions": {
                name: QRect(rect) for name, rect in self.json_regions.items()
            },
            "json_region_centers": {
                name: QPointF(offset)
                for name, offset in self.json_region_centers.items()
            },
            "json_region_scales": {
                name: QPointF(scale)
                for name, scale in self.json_region_scales.items()
            },
            "json_region_mipmaps": dict(self.json_region_mipmaps),
            "imported_bounds": QRect(self.imported_bounds) if self.imported_bounds else None,
            "document_initialized": self.document_initialized,
        }

    def _restore_state(self, state):
        self.main_layer = state["image"]
        self.layer_origin = QPoint(state["origin"])
        self.selection_rect = QRect(state["selection"]) if state["selection"] else None
        self.vector_points = state["points"].copy()
        self.floating_layer = state["floating"].copy() if state["floating"] else None
        self.json_regions = {
            name: QRect(rect) for name, rect in state.get("json_regions", {}).items()
        }
        saved_centers = state.get("json_region_centers", {})
        self.json_region_centers = {
            name: QPointF(saved_centers.get(name, QPointF(0, 0)))
            for name in self.json_regions
        }
        saved_scales = state.get("json_region_scales", {})
        self.json_region_scales = {
            name: QPointF(saved_scales.get(name, QPointF(1, 1)))
            for name in self.json_regions
        }
        saved_mipmaps = state.get("json_region_mipmaps", {})
        self.json_region_mipmaps = {
            name: bool(saved_mipmaps.get(name, False))
            for name in self.json_regions
        }
        imported = state.get("imported_bounds")
        self.imported_bounds = QRect(imported) if imported else None
        self.document_initialized = state.get("document_initialized", True)

    # ------------------------------------------------------------------
    # Canvas storage
    # ------------------------------------------------------------------
    def ensure_canvas_contains_rect(self, required_rect):
        """Grow the backing image exactly to contain a half-open world QRect."""
        if not required_rect or required_rect.isEmpty():
            return
        current = self.canvas_rect()
        combined = current.united(required_rect)
        if combined == current:
            return

        new_img = self._new_empty_image(combined.width(), combined.height())
        offset_x = current.x() - combined.x()
        offset_y = (combined.y() + combined.height()) - (
            current.y() + current.height()
        )
        painter = QPainter(new_img)
        painter.drawImage(offset_x, offset_y, self.main_layer)
        painter.end()

        self.main_layer = new_img
        self.layer_origin = QPoint(combined.x(), combined.y())

    def ensure_canvas_covers(self, x, y):
        """Ensure the world pixel at integer coordinate (x, y) exists."""
        self.ensure_canvas_contains_rect(QRect(x, y, 1, 1))

    def set_pixel(self, x, y, color):
        self.ensure_canvas_covers(x, y)
        ox, oy = self.layer_origin.x(), self.layer_origin.y()
        h = self.main_layer.height()
        self.main_layer.setPixelColor(x - ox, oy + h - 1 - y, color)
        if color.alpha() > 0:
            self.document_initialized = True

    def erase_pixel(self, x, y):
        self.set_pixel(x, y, QColor(0, 0, 0, 0))

    def get_pixel_color(self, x, y):
        """Return the raw ARGB color of one world-space texel.

        Pixels outside the backing image are treated as fully transparent.
        """
        if not self.canvas_rect().contains(x, y):
            return QColor(0, 0, 0, 0)
        ox, oy = self.layer_origin.x(), self.layer_origin.y()
        image_y = oy + self.main_layer.height() - 1 - y
        return self.main_layer.pixelColor(x - ox, image_y)

    def clear_canvas(self):
        self.push_undo_state()
        self.main_layer = self._new_empty_image(DEFAULT_WIDTH, DEFAULT_HEIGHT)
        self.layer_origin = self._default_origin(DEFAULT_HEIGHT)
        self.selection_rect = None
        self.vector_points.clear()
        self.floating_layer = None
        self.json_regions.clear()
        self.json_region_centers.clear()
        self.json_region_scales.clear()
        self.json_region_mipmaps.clear()
        self.imported_bounds = None
        self.document_initialized = False

    def is_canvas_empty(self):
        return not self.document_initialized

    def _draw_world_image(self, world_rect, image):
        self.ensure_canvas_contains_rect(world_rect)
        ox, oy = self.layer_origin.x(), self.layer_origin.y()
        canvas_h = self.main_layer.height()
        dest_x = world_rect.x() - ox
        dest_y = oy + canvas_h - (world_rect.y() + world_rect.height())
        painter = QPainter(self.main_layer)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.drawImage(dest_x, dest_y, image)
        painter.end()

    def load_image(self, img):
        if img.isNull():
            return
        self.push_undo_state()
        self.main_layer = img.copy()
        width, height = img.width(), img.height()
        self.layer_origin = QPoint(0, -height if self.coordinate_mode.y_down else 0)
        self.selection_rect = QRect(self.layer_origin.x(), self.layer_origin.y(), width, height)
        self.imported_bounds = QRect(self.selection_rect)
        self.vector_points.clear()
        self.floating_layer = None
        # Keep regions when the JSON was imported before the first texture.
        self.document_initialized = True

    def append_image_right(self, img):
        """Append tightly to the right of prior imports, independent of buffer growth."""
        if img.isNull():
            return
        if self.is_canvas_empty():
            self.load_image(img)
            return

        self.push_undo_state()
        base = QRect(self.imported_bounds) if self.imported_bounds else self.canvas_rect()
        start_x = base.x() + base.width()
        if self.coordinate_mode.y_down:
            start_y = base.y() + base.height() - img.height()  # top aligned
        else:
            start_y = base.y()  # bottom aligned

        image_rect = QRect(start_x, start_y, img.width(), img.height())
        self._draw_world_image(image_rect, img)
        self.imported_bounds = base.united(image_rect)
        self.selection_rect = QRect(image_rect)
        self.document_initialized = True

    def place_image_at(self, img, bottom_left):
        """Place an imported image with its lower-left corner at bottom_left."""
        if img.isNull():
            return False
        self.push_undo_state()
        image_rect = QRect(
            int(bottom_left.x()),
            int(bottom_left.y()),
            img.width(),
            img.height(),
        )
        self._draw_world_image(image_rect, img)
        if self.imported_bounds:
            self.imported_bounds = self.imported_bounds.united(image_rect)
        else:
            self.imported_bounds = QRect(image_rect)
        self.selection_rect = QRect(image_rect)
        self.floating_layer = None
        self.document_initialized = True
        return True

    # ------------------------------------------------------------------
    # JSON regions
    # ------------------------------------------------------------------
    def load_json_regions(self, regions_dict, merge=False):
        if not isinstance(regions_dict, dict):
            raise ValueError("JSON 根节点必须是对象")
        loaded = (
            {name: QRect(rect) for name, rect in self.json_regions.items()}
            if merge
            else {}
        )
        loaded_centers = (
            {
                name: QPointF(
                    self.json_region_centers.get(name, QPointF(0, 0))
                )
                for name in loaded
            }
            if merge
            else {}
        )
        loaded_scales = (
            {
                name: QPointF(
                    self.json_region_scales.get(name, QPointF(1, 1))
                )
                for name in loaded
            }
            if merge
            else {}
        )
        loaded_mipmaps = (
            {
                name: bool(self.json_region_mipmaps.get(name, False))
                for name in loaded
            }
            if merge
            else {}
        )
        imported_names = []
        for name, region in regions_dict.items():
            if not isinstance(region, dict) or not all(
                key in region for key in ("x", "y", "w", "h")
            ):
                continue
            try:
                x = int(region["x"])
                y = int(region["y"])
                width = int(region["w"])
                height = int(region["h"])
                center_dx = float(region.get("center_dx", 0))
                center_dy = float(region.get("center_dy", 0))
                hscale = float(region.get("hscale", 1))
                vscale = float(region.get("vscale", 1))
                mipmap = region.get("mipmap", False)
            except (TypeError, ValueError):
                continue
            if (
                width <= 0
                or height <= 0
                or not math.isfinite(center_dx)
                or not math.isfinite(center_dy)
                or not math.isfinite(hscale)
                or not math.isfinite(vscale)
                or not isinstance(mipmap, bool)
            ):
                continue
            if self.coordinate_mode.y_down:
                world_y = -(y + height)
            else:
                world_y = y
            region_name = str(name)
            loaded[region_name] = QRect(x, world_y, width, height)
            world_center_dy = -center_dy if self.coordinate_mode.y_down else center_dy
            loaded_centers[region_name] = QPointF(center_dx, world_center_dy)
            loaded_scales[region_name] = QPointF(hscale, vscale)
            loaded_mipmaps[region_name] = mipmap
            imported_names.append(region_name)

        if merge and not imported_names:
            return []
        self.push_undo_state()
        self.json_regions = loaded
        self.json_region_centers = loaded_centers
        self.json_region_scales = loaded_scales
        self.json_region_mipmaps = loaded_mipmaps
        return imported_names

    def export_json_regions(self):
        result = {}
        for name, rect in self.json_regions.items():
            if self.coordinate_mode.y_down:
                y = -(rect.y() + rect.height())
            else:
                y = rect.y()
            center = self.json_region_centers.get(name, QPointF(0, 0))
            center_dx = center.x()
            center_dy = -center.y() if self.coordinate_mode.y_down else center.y()
            scale = self.json_region_scales.get(name, QPointF(1, 1))
            result[name] = {
                "x": rect.x(),
                "y": y,
                "w": rect.width(),
                "h": rect.height(),
                "center_dx": self._compact_json_number(center_dx),
                "center_dy": self._compact_json_number(center_dy),
                "hscale": self._compact_json_number(scale.x()),
                "vscale": self._compact_json_number(scale.y()),
                "mipmap": bool(self.json_region_mipmaps.get(name, False)),
            }
        return result

    @staticmethod
    def _compact_json_number(value):
        value = float(value)
        return int(value) if value.is_integer() else value

    # ------------------------------------------------------------------
    # Selection transforms
    # ------------------------------------------------------------------
    def _clear_world_rect(self, rect):
        intersection = rect.intersected(self.canvas_rect())
        if intersection.isEmpty():
            return
        ox, oy = self.layer_origin.x(), self.layer_origin.y()
        canvas_h = self.main_layer.height()
        src_x = intersection.x() - ox
        src_y = oy + canvas_h - (intersection.y() + intersection.height())
        painter = QPainter(self.main_layer)
        painter.setCompositionMode(QPainter.CompositionMode_Clear)
        painter.fillRect(src_x, src_y, intersection.width(), intersection.height(), Qt.transparent)
        painter.end()

    def rotate_selection_inplace(self, clockwise=True):
        if not self.selection_rect:
            return
        rect = QRect(self.selection_rect)
        sub_img = self.get_image(rect)
        if sub_img.isNull():
            return
        self.push_undo_state()
        self._clear_world_rect(rect)

        transform = QTransform().rotate(90 if clockwise else -90)
        rotated_img = sub_img.transformed(transform, Qt.FastTransformation)
        new_rect = QRect(rect.x(), rect.y(), rotated_img.width(), rotated_img.height())
        self._draw_world_image(new_rect, rotated_img)
        self.selection_rect = new_rect
        self.floating_layer = None
        self.document_initialized = True

    def flip_selection_inplace(self, horizontal=True):
        if not self.selection_rect:
            return
        rect = QRect(self.selection_rect)
        sub_img = self.get_image(rect)
        if sub_img.isNull():
            return
        self.push_undo_state()
        self._clear_world_rect(rect)
        flipped_img = sub_img.mirrored(horizontal, not horizontal)
        self._draw_world_image(rect, flipped_img)
        self.floating_layer = None

    def scale_selection_inplace(
        self,
        scale_x,
        scale_y,
        sampling="bilinear",
        center="bottom_left",
        target_width=None,
        target_height=None,
    ):
        if not self.selection_rect:
            return False

        rect = QRect(self.selection_rect)
        source = self.get_image(rect)
        if source.isNull():
            return False

        new_width = (
            max(1, int(target_width))
            if target_width is not None
            else max(1, round(rect.width() * float(scale_x)))
        )
        new_height = (
            max(1, int(target_height))
            if target_height is not None
            else max(1, round(rect.height() * float(scale_y)))
        )
        if new_width > 100000 or new_height > 100000:
            raise ValueError("缩放后的选区尺寸不能超过 100000 × 100000 像素")
        if new_width == rect.width() and new_height == rect.height():
            return False

        transform_mode = (
            Qt.SmoothTransformation
            if sampling == "bilinear"
            else Qt.FastTransformation
        )
        scaled = source.scaled(
            new_width, new_height, Qt.IgnoreAspectRatio, transform_mode
        )

        left = rect.x()
        right = rect.x() + rect.width()
        bottom = rect.y()
        top = rect.y() + rect.height()
        if center == "top_left":
            new_x, new_y = left, top - new_height
        elif center == "center":
            new_x = round(left + (rect.width() - new_width) / 2)
            new_y = round(bottom + (rect.height() - new_height) / 2)
        elif center == "top_right":
            new_x, new_y = right - new_width, top - new_height
        elif center == "bottom_right":
            new_x, new_y = right - new_width, bottom
        else:
            new_x, new_y = left, bottom
        new_rect = QRect(new_x, new_y, new_width, new_height)

        self.push_undo_state()
        self._clear_world_rect(rect)
        self._draw_world_image(new_rect, scaled)
        self.selection_rect = new_rect
        self.floating_layer = None
        self.document_initialized = True
        return True

    def overlay_selection_color(self, color, blend_mode="normal"):
        color = QColor(color)
        if (
            not self.selection_rect
            or not color.isValid()
            or (color.alpha() == 0 and blend_mode != "replace")
        ):
            return False

        rect = QRect(self.selection_rect)
        source = self.get_image(rect)
        if source.isNull():
            return False

        blended = blend_color_image(source, color, blend_mode)
        if blended.isNull():
            return False

        self.push_undo_state()
        self._clear_world_rect(rect)
        self._draw_world_image(rect, blended)
        self.floating_layer = None
        self.document_initialized = True
        return True

    def lift_selection(self):
        if not self.selection_rect:
            return
        rect = self.selection_rect
        self.floating_layer = self.get_image(rect)
        self._clear_world_rect(rect)

    def drop_selection(self, dx, dy):
        if not self.floating_layer or not self.selection_rect:
            self.floating_layer = None
            return
        new_rect = QRect(self.selection_rect)
        new_rect.translate(dx, dy)
        self._draw_world_image(new_rect, self.floating_layer)
        self.selection_rect = new_rect
        self.floating_layer = None
        self.document_initialized = True

    def delete_selection(self):
        if self.floating_layer:
            # The pre-lift state was already pushed when movement started.
            self.floating_layer = None
            return
        if self.selection_rect:
            self.push_undo_state()
            self._clear_world_rect(self.selection_rect)

    def copy_selection(self, anchor_grid_pos):
        if not self.selection_rect:
            return
        self.clipboard_anchor_offset = anchor_grid_pos - self.selection_rect.topLeft()
        self.clipboard_image = self.get_image(self.selection_rect)

    def cut_selection(self, anchor_grid_pos):
        if not self.selection_rect:
            return
        self.copy_selection(anchor_grid_pos)
        self.delete_selection()

    def paste_from_clipboard(self, target_grid_pos):
        if not self.clipboard_image:
            return
        self.push_undo_state()
        top_left = target_grid_pos - self.clipboard_anchor_offset
        width, height = self.clipboard_image.width(), self.clipboard_image.height()
        self.floating_layer = self.clipboard_image.copy()
        self.selection_rect = QRect(top_left.x(), top_left.y(), width, height)
        self.ensure_canvas_contains_rect(self.selection_rect)

    def get_content_rect(self):
        return self.canvas_rect()

    def get_image(self, rect):
        """Return an exact-size image, padding out-of-canvas areas transparently."""
        if not rect or rect.isEmpty():
            return QImage()
        output = self._new_empty_image(rect.width(), rect.height())
        intersection = rect.intersected(self.canvas_rect())
        if intersection.isEmpty():
            return output

        ox, oy = self.layer_origin.x(), self.layer_origin.y()
        canvas_h = self.main_layer.height()
        src_x = intersection.x() - ox
        src_y = oy + canvas_h - (intersection.y() + intersection.height())
        dest_x = intersection.x() - rect.x()
        dest_y = (rect.y() + rect.height()) - (
            intersection.y() + intersection.height()
        )

        painter = QPainter(output)
        painter.drawImage(
            dest_x,
            dest_y,
            self.main_layer,
            src_x,
            src_y,
            intersection.width(),
            intersection.height(),
        )
        painter.end()
        return output
