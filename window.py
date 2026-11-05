import json
import os

from PyQt5.QtWidgets import (
    QMainWindow,
    QAction,
    QFileDialog,
    QColorDialog,
    QLabel,
    QToolBar,
    QActionGroup,
    QDialog,
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QGridLayout,
    QPushButton,
    QMessageBox,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
    QGroupBox,
    QMenu,
    QLineEdit,
    QDoubleSpinBox,
    QCheckBox,
    QShortcut,
    QApplication,
    QSizePolicy,
    QStyle,
    QStyleOptionViewItem,
)
from PyQt5.QtGui import QColor, QImage, QKeySequence
from PyQt5.QtCore import (
    Qt,
    QPoint,
    QPointF,
    QRect,
    QEvent,
    QSettings,
    QTimer,
    QItemSelectionModel,
)

from consts import ToolType, CoordinateMode
from canvas import TextureCanvas
from dialogs import ExportDialog


class ClickToCopyLabel(QLabel):
    """Selectable label that copies its complete value on a plain click."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._press_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_pos = event.pos()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        press_pos = self._press_pos
        self._press_pos = None
        super().mouseReleaseEvent(event)

        if event.button() != Qt.LeftButton or press_pos is None:
            return
        if (event.pos() - press_pos).manhattanLength() > QApplication.startDragDistance():
            return

        value = self.text().strip()
        if not value or value == "—":
            return

        QApplication.clipboard().setText(value)
        window = self.window()
        if isinstance(window, QMainWindow):
            window.statusBar().showMessage(f"已复制: {value}", 1500)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PixelEditor ver 8.3 by phsonh")
        self.resize(1300, 800)
        self.setAcceptDrops(True)

        self.settings = QSettings("phsonh", "PixelEditor")

        self.canvas = TextureCanvas(self)
        self.setCentralWidget(self.canvas)

        self.status_lbl = QLabel()
        self.statusBar().addPermanentWidget(self.status_lbl)

        self.is_editing_json = False
        self._control_key_down = False
        self._ctrl_delete_consumed = False
        self.editing_json_original_name = None
        self.json_clipboard_rect = None
        self.json_clipboard_name = None
        self.json_clipboard_center = None
        self.json_clipboard_scale = None
        self.json_clipboard_mipmap = False
        self.last_json_region_name = None
        self.opened_image_paths = []
        self.opened_json_paths = []
        self.last_opened_directory = None

        self.canvas.installEventFilter(self)
        self.create_property_panel()

        self.action_map = {}
        self.create_toolbar()
        self.create_menu()
        self.create_shortcuts()

        saved_mode = self.settings.value(
            "coordinate_mode", CoordinateMode.TOP_LEFT_Y_DOWN.value, type=str
        )
        try:
            mode = CoordinateMode(saved_mode)
        except ValueError:
            mode = CoordinateMode.TOP_LEFT_Y_DOWN
        self.set_coordinate_mode(mode, persist=False, refit=False)
        self.update_selection_ui()
        QApplication.instance().installEventFilter(self)

    # ------------------------------------------------------------------
    # Property panel
    # ------------------------------------------------------------------
    def create_property_panel(self):
        dock = QDockWidget("属性/裁剪控制", self)
        dock.setAllowedAreas(Qt.RightDockWidgetArea)
        panel = QWidget()
        panel.setMinimumWidth(320)
        layout = QVBoxLayout(panel)

        color_group = QGroupBox("画笔颜色")
        color_layout = QVBoxLayout(color_group)
        self.current_color_button = QPushButton()
        self.current_color_button.setMinimumHeight(36)
        self.current_color_button.clicked.connect(self.pick_color)
        color_layout.addWidget(self.current_color_button)

        palette_widget = QWidget()
        palette_layout = QGridLayout(palette_widget)
        palette_layout.setContentsMargins(0, 0, 0, 0)
        palette_layout.setHorizontalSpacing(5)
        palette_layout.setVerticalSpacing(5)
        palette_colors = (
            "#000000", "#404040", "#808080", "#c0c0c0", "#ffffff",
            "#7f0000", "#ff0000", "#ff7f00", "#ffff00", "#7fff00",
            "#008000", "#00ff80", "#00ffff", "#0080ff", "#0000ff",
            "#400080", "#8000ff", "#ff00ff", "#ff0080", "#7f3f00",
        )
        self.palette_buttons = []
        for index, color_name in enumerate(palette_colors):
            color = QColor(color_name)
            button = QPushButton()
            button.setFixedSize(28, 28)
            button.setToolTip(color_name.upper())
            button.setStyleSheet(
                f"background-color: {color_name}; border: 1px solid #666; "
                "border-radius: 3px;"
            )
            button.clicked.connect(
                lambda checked=False, selected=color: self.set_current_color(selected)
            )
            palette_layout.addWidget(button, index // 5, index % 5)
            self.palette_buttons.append(button)
        color_layout.addWidget(palette_widget, alignment=Qt.AlignHCenter)
        layout.addWidget(color_group)
        self.refresh_current_color_ui()

        selected_pixel_group = QGroupBox("当前选中像素块")
        selected_pixel_layout = QGridLayout(selected_pixel_group)
        self.selected_pixel_coordinate_values = {}
        self.selected_pixel_argb_value = ClickToCopyLabel("—")

        # Keep the same font family as the rest of the application.  Ignoring
        # the changing text size hint keeps the dock stable while the four
        # coordinate values gain or lose digits.
        pixel_value_font = self.selected_pixel_argb_value.font()
        pixel_value_font.setBold(True)

        corner_specs = (
            ("top_left", "左上", 0, Qt.AlignLeft | Qt.AlignVCenter),
            ("top_right", "右上", 1, Qt.AlignRight | Qt.AlignVCenter),
            ("bottom_left", "左下", 0, Qt.AlignLeft | Qt.AlignVCenter),
            ("bottom_right", "右下", 1, Qt.AlignRight | Qt.AlignVCenter),
        )
        for key, title, column, alignment in corner_specs:
            title_row = 0 if key.startswith("top") else 2
            value_row = title_row + 1
            title_label = QLabel(title)
            title_label.setStyleSheet("color: #888;")
            title_label.setAlignment(alignment)
            value_label = ClickToCopyLabel("—")
            value_label.setAlignment(alignment)
            self.selected_pixel_coordinate_values[key] = value_label
            selected_pixel_layout.addWidget(title_label, title_row, column)
            selected_pixel_layout.addWidget(value_label, value_row, column)

        for value_label in (
            *self.selected_pixel_coordinate_values.values(),
            self.selected_pixel_argb_value,
        ):
            value_label.setFont(pixel_value_font)
            value_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            # Preserve the label-like appearance while allowing users to
            # select the value with the mouse and copy it with Ctrl+C.
            value_label.setTextInteractionFlags(
                Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
            )
            value_label.setFocusPolicy(Qt.StrongFocus)
            value_label.setCursor(Qt.IBeamCursor)

        self.selected_pixel_argb_value.setWordWrap(False)
        selected_pixel_layout.setColumnStretch(0, 1)
        selected_pixel_layout.setColumnStretch(1, 1)
        selected_pixel_layout.setColumnStretch(2, 0)

        self.selection_height_value = QLabel("H\n—")
        self.selection_height_value.setAlignment(Qt.AlignCenter)
        self.selection_height_value.setMinimumWidth(58)
        self.selection_height_value.setStyleSheet(
            "font-weight: bold; border-left: 1px solid palette(mid); "
            "padding-left: 8px;"
        )
        selected_pixel_layout.addWidget(
            self.selection_height_value, 0, 2, 4, 1
        )

        self.selection_width_value = QLabel("W: —")
        self.selection_width_value.setAlignment(Qt.AlignCenter)
        self.selection_width_value.setStyleSheet(
            "font-weight: bold; border-top: 1px solid palette(mid); "
            "padding-top: 6px;"
        )
        selected_pixel_layout.addWidget(
            self.selection_width_value, 4, 0, 1, 2
        )

        selected_pixel_layout.addWidget(QLabel("ARGB:"), 5, 0)
        self.selected_pixel_argb_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        selected_pixel_layout.addWidget(self.selected_pixel_argb_value, 5, 1)
        layout.addWidget(selected_pixel_group)

        layout.addSpacing(10)

        self.edit_region_name = QLineEdit()
        self.edit_region_name.setPlaceholderText("在此输入纹理名称...")
        self.edit_region_name.setVisible(False)
        self.edit_region_name.installEventFilter(self)
        layout.addWidget(self.edit_region_name)

        self.center_offset_group = QGroupBox("旋转 / 缩放中心偏移")
        center_offset_layout = QGridLayout(self.center_offset_group)
        self.center_dx_spin = QDoubleSpinBox()
        self.center_dy_spin = QDoubleSpinBox()
        self._loading_center_offsets = False
        self._center_dx_edited = False
        self._center_dy_edited = False
        for spin in (self.center_dx_spin, self.center_dy_spin):
            spin.setRange(-99999.00, 99999.00)
            spin.setDecimals(2)
            spin.setSingleStep(0.50)
            spin.setSuffix(" px")
            spin.installEventFilter(self)
            spin.lineEdit().installEventFilter(self)
        center_offset_layout.addWidget(QLabel("center_dx:"), 0, 0)
        center_offset_layout.addWidget(self.center_dx_spin, 0, 1)
        center_offset_layout.addWidget(QLabel("center_dy:"), 1, 0)
        center_offset_layout.addWidget(self.center_dy_spin, 1, 1)
        center_hint = QLabel("相对切片几何中心（使用当前 JSON 坐标系）")
        center_hint.setStyleSheet("color: #888;")
        center_hint.setWordWrap(True)
        center_offset_layout.addWidget(center_hint, 2, 0, 1, 2)
        self.center_dx_spin.valueChanged.connect(
            lambda: self._mark_center_offset_edited("x")
        )
        self.center_dy_spin.valueChanged.connect(
            lambda: self._mark_center_offset_edited("y")
        )
        self.center_offset_group.setVisible(False)
        layout.addWidget(self.center_offset_group)

        self.json_scale_group = QGroupBox("切片缩放参数（仅 JSON）")
        json_scale_layout = QGridLayout(self.json_scale_group)
        self.hscale_spin = QDoubleSpinBox()
        self.vscale_spin = QDoubleSpinBox()
        self._loading_json_scales = False
        self._hscale_edited = False
        self._vscale_edited = False
        for spin in (self.hscale_spin, self.vscale_spin):
            spin.setRange(-99999.00, 99999.00)
            spin.setDecimals(2)
            spin.setSingleStep(0.10)
            spin.installEventFilter(self)
            spin.lineEdit().installEventFilter(self)
        json_scale_layout.addWidget(QLabel("hscale:"), 0, 0)
        json_scale_layout.addWidget(self.hscale_spin, 0, 1)
        json_scale_layout.addWidget(QLabel("vscale:"), 1, 0)
        json_scale_layout.addWidget(self.vscale_spin, 1, 1)
        self.mipmap_checkbox = QCheckBox("启用")
        self.mipmap_checkbox.installEventFilter(self)
        json_scale_layout.addWidget(QLabel("mipmap:"), 2, 0)
        json_scale_layout.addWidget(self.mipmap_checkbox, 2, 1)
        scale_hint = QLabel("仅保存到 JSON，不影响编辑器中的画布内容")
        scale_hint.setStyleSheet("color: #888;")
        scale_hint.setWordWrap(True)
        json_scale_layout.addWidget(scale_hint, 3, 0, 1, 2)
        self.hscale_spin.valueChanged.connect(
            lambda: self._mark_json_scale_edited("h")
        )
        self.vscale_spin.valueChanged.connect(
            lambda: self._mark_json_scale_edited("v")
        )
        self.json_scale_group.setVisible(False)
        layout.addWidget(self.json_scale_group)

        self.btn_action = QPushButton("✂ 裁剪并保存选区")
        self.btn_action.setFixedHeight(45)
        self.btn_action.setStyleSheet(
            "background-color: #2c3e50; color: white; font-weight: bold;"
        )
        self.btn_action.clicked.connect(self.on_btn_action_clicked)
        layout.addWidget(self.btn_action)

        self.btn_cancel = QPushButton("放弃修改并退出")
        self.btn_cancel.setFixedHeight(30)
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self.exit_edit_json_mode)
        layout.addWidget(self.btn_cancel)

        layout.addSpacing(10)
        layout.addWidget(QLabel("JSON 切片区域（右键可操作）:"))
        self.region_list = QListWidget()
        self.region_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.region_list.installEventFilter(self)
        self.region_list.viewport().installEventFilter(self)
        self.region_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.region_list.customContextMenuRequested.connect(
            self.show_list_context_menu
        )
        self.region_list.itemClicked.connect(self.on_region_selected)
        layout.addWidget(self.region_list)

        layout.addStretch()
        dock.setWidget(panel)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    def eventFilter(self, watched, event):
        region_list = getattr(self, "region_list", None)
        region_viewport = region_list.viewport() if region_list is not None else None
        name_editor = getattr(self, "edit_region_name", None)
        dx_spin = getattr(self, "center_dx_spin", None)
        dy_spin = getattr(self, "center_dy_spin", None)
        hscale_spin = getattr(self, "hscale_spin", None)
        vscale_spin = getattr(self, "vscale_spin", None)
        mipmap_checkbox = getattr(self, "mipmap_checkbox", None)
        json_editors = {
            name_editor,
            dx_spin,
            dy_spin,
            hscale_spin,
            vscale_spin,
            mipmap_checkbox,
        }
        for spin in (dx_spin, dy_spin, hscale_spin, vscale_spin):
            if spin is not None:
                json_editors.add(spin.lineEdit())

        if event.type() in (QEvent.ApplicationDeactivate, QEvent.WindowDeactivate):
            self._control_key_down = False

        is_editor_widget = (
            isinstance(watched, QWidget) and watched.window() is self
        )
        if (
            is_editor_widget
            and event.type() in (QEvent.KeyPress, QEvent.KeyRelease)
            and event.key() == Qt.Key_Control
        ):
            if event.type() == QEvent.KeyPress:
                self._control_key_down = True
            else:
                self._control_key_down = False
                self._ctrl_delete_consumed = False

        if (
            is_editor_widget
            and event.type() == QEvent.KeyRelease
            and event.key() == Qt.Key_Delete
        ):
            self._ctrl_delete_consumed = False

        if (
            is_editor_widget
            and event.type() in (QEvent.ShortcutOverride, QEvent.KeyPress)
            and event.key() == Qt.Key_Delete
            and not event.isAutoRepeat()
            and (
                event.modifiers() & Qt.ControlModifier
                or self._control_key_down
            )
        ):
            self.trigger_ctrl_delete()
            event.accept()
            return event.type() == QEvent.KeyPress

        if (
            watched is region_viewport
            and event.type() == QEvent.MouseButtonPress
            and event.button() == Qt.LeftButton
        ):
            item = region_list.itemAt(event.pos())
            if item is None:
                self.clear_json_region_checks()
                region_list.clearSelection()
                region_list.setCurrentRow(-1)
            else:
                check_rect = self.json_region_check_indicator_rect(item)
                if check_rect.contains(event.pos()):
                    checked = item.checkState() != Qt.Checked
                    item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
                    region_list.selectionModel().setCurrentIndex(
                        region_list.indexFromItem(item),
                        QItemSelectionModel.NoUpdate,
                    )
                    item.setSelected(checked)
                else:
                    self.clear_json_region_checks()
                    region_list.clearSelection()
                    region_list.setCurrentItem(item)
                    item.setSelected(True)
                    item.setCheckState(Qt.Checked)
                self.on_region_selected(item)
            event.accept()
            return True

        if (
            watched is region_list
            and event.type() == QEvent.KeyPress
            and event.key() == Qt.Key_A
            and event.modifiers() & Qt.ControlModifier
        ):
            self.check_all_json_regions()
            event.accept()
            return True

        delete_targets = json_editors | {region_list, self.canvas}
        if (
            watched in delete_targets
            and event.type() == QEvent.KeyPress
            and event.key() == Qt.Key_Delete
        ):
            if watched is region_list:
                self.delete_selected_json_regions()
            elif watched is self.canvas:
                self.canvas.delete_selection()
            elif self.is_editing_json:
                self.delete_current_context()
            event.accept()
            return True

        return super().eventFilter(watched, event)

    def set_coordinate_mode(self, mode, persist=True, refit=True):
        if not isinstance(mode, CoordinateMode):
            mode = CoordinateMode(mode)

        old_origin_x = self.canvas.model.layer_origin.x()
        old_origin_y = self.canvas.model.layer_origin.y()
        changed = self.canvas.model.set_coordinate_mode(mode, reanchor=True)
        if changed and self.is_editing_json:
            was_edited = self._center_dy_edited
            self._loading_center_offsets = True
            self.center_dy_spin.setValue(-self.center_dy_spin.value())
            self._loading_center_offsets = False
            self._center_dy_edited = was_edited
        if changed and self.canvas.selected_pixel_world is not None:
            dx = self.canvas.model.layer_origin.x() - old_origin_x
            dy = self.canvas.model.layer_origin.y() - old_origin_y
            selected_x, selected_y = self.canvas.selected_pixel_world
            self.canvas.selected_pixel_world = (selected_x + dx, selected_y + dy)

        if hasattr(self, "action_coordinate_top_left"):
            self.action_coordinate_top_left.setChecked(
                mode is CoordinateMode.TOP_LEFT_Y_DOWN
            )
            self.action_coordinate_bottom_left.setChecked(
                mode is CoordinateMode.BOTTOM_LEFT_Y_UP
            )

        if persist:
            self.settings.setValue("coordinate_mode", mode.value)

        self.update_selection_ui()
        self.canvas.update()
        if changed and refit and self.canvas.model.document_initialized:
            self.canvas.fit_to_rect(self.canvas.model.get_content_rect())

    def update_mouse_status(self, world_x, world_y, zoom, hovering=True):
        arrow = "↓" if self.canvas.model.coordinate_mode.y_down else "↑"
        if hovering and world_x is not None and world_y is not None:
            display_x, display_y = self.canvas.model.world_pixel_to_display(
                world_x, world_y
            )
            self.status_lbl.setText(
                f"Pos: ({int(display_x)}, {int(display_y)}) | "
                f"Y{arrow} | Zoom: {zoom:.1f}"
            )
        else:
            self.status_lbl.setText(f"Pos: — | Y{arrow} | Zoom: {zoom:.1f}")

    def update_selected_pixel_ui(self, world_x, world_y, color):
        rect = None
        if world_x is not None and world_y is not None:
            rect = QRect(int(world_x), int(world_y), 1, 1)
        self.update_selected_region_ui(rect, color)

    def update_selected_region_ui(self, world_rect, color=None):
        if world_rect is None or world_rect.isEmpty():
            for value_label in self.selected_pixel_coordinate_values.values():
                value_label.setText("—")
                value_label.setToolTip("")
            self.selection_width_value.setText("W: —")
            self.selection_height_value.setText("H\n—")
            self.selected_pixel_argb_value.setText("—")
            self.selected_pixel_argb_value.setToolTip("")
            return

        self.selection_width_value.setText(f"W: {world_rect.width()} px")
        self.selection_height_value.setText(f"H\n{world_rect.height()} px")
        left = world_rect.x()
        right = left + world_rect.width()
        bottom = world_rect.y()
        top = bottom + world_rect.height()
        corners = {
            "top_left": (left, top),
            "top_right": (right, top),
            "bottom_left": (left, bottom),
            "bottom_right": (right, bottom),
        }
        for key, (corner_x, corner_y) in corners.items():
            display_x, display_y = self.canvas.model.world_to_display(
                corner_x, corner_y
            )
            coordinate_text = f"({int(display_x)}, {int(display_y)})"
            value_label = self.selected_pixel_coordinate_values[key]
            value_label.setText(coordinate_text)
            value_label.setToolTip(f"点击复制：{coordinate_text}")

        is_single_pixel = world_rect.width() == 1 and world_rect.height() == 1
        if not is_single_pixel or color is None:
            self.selected_pixel_argb_value.setText("—")
            self.selected_pixel_argb_value.setToolTip("")
            return

        argb_text = (
            f"({color.alpha()},{color.red()},"
            f"{color.green()},{color.blue()})"
        )
        self.selected_pixel_argb_value.setText(argb_text)
        self.selected_pixel_argb_value.setToolTip(f"点击复制：{argb_text}")

    def update_selection_size_ui(self):
        rect = self.canvas.model.selection_rect
        if rect and not rect.isEmpty():
            self.selection_width_value.setText(f"W: {rect.width()} px")
            self.selection_height_value.setText(f"H\n{rect.height()} px")
        else:
            self.selection_width_value.setText("W: —")
            self.selection_height_value.setText("H\n—")

    def update_selection_ui(self):
        self.update_selection_size_ui()
        self.canvas.refresh_selected_pixel_ui()

    # ------------------------------------------------------------------
    # JSON region list
    # ------------------------------------------------------------------
    def show_list_context_menu(self, pos):
        item = self.region_list.itemAt(pos)
        menu = QMenu(self)
        action_mod = action_del = action_copy = None
        if item:
            action_mod = menu.addAction("修改\tF2")
            action_del = menu.addAction("删除\tDelete")
            action_copy = menu.addAction("复制")
            menu.addSeparator()
        action_new = menu.addAction("新建\tCtrl+J")
        action_paste = menu.addAction("粘贴")
        action_paste.setEnabled(self.json_clipboard_rect is not None)
        menu.addSeparator()
        action_export = menu.addAction("导出 JSON...\tCtrl+Shift+S")
        action = menu.exec_(self.region_list.mapToGlobal(pos))

        if item:
            name = item.text()
            if action == action_mod:
                self.start_edit_json_region(name)
            elif action == action_del:
                target_names = self.selected_or_checked_json_region_names()
                if name not in target_names:
                    target_names = [name]
                self.delete_json_regions(target_names)
            elif action == action_copy:
                self.copy_json_region(name)
        if action == action_new:
            self.start_edit_json_region(None)
        elif action == action_paste:
            self.paste_json_region()
        elif action == action_export:
            self.export_json()

    def refresh_region_list(self):
        selected_names = {
            item.text() for item in self.region_list.selectedItems()
        }
        checked_names = {
            self.region_list.item(index).text()
            for index in range(self.region_list.count())
            if self.region_list.item(index).checkState() == Qt.Checked
        }
        current_item = self.region_list.currentItem()
        current_name = current_item.text() if current_item else None
        self.region_list.clear()
        for name in self.canvas.model.json_regions:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(
                Qt.Checked if name in checked_names else Qt.Unchecked
            )
            self.region_list.addItem(item)
        if current_name:
            matches = self.region_list.findItems(current_name, Qt.MatchExactly)
            if matches:
                self.region_list.setCurrentItem(matches[0])
        for index in range(self.region_list.count()):
            item = self.region_list.item(index)
            item.setSelected(item.text() in selected_names)
        self.canvas.update()

    def clear_json_region_checks(self):
        for index in range(self.region_list.count()):
            item = self.region_list.item(index)
            if item.checkState() != Qt.Unchecked:
                item.setCheckState(Qt.Unchecked)

    def json_region_check_indicator_rect(self, item):
        option = QStyleOptionViewItem()
        self.region_list.itemDelegate().initStyleOption(
            option, self.region_list.indexFromItem(item)
        )
        option.rect = self.region_list.visualItemRect(item)
        return self.region_list.style().subElementRect(
            QStyle.SE_ItemViewItemCheckIndicator,
            option,
            self.region_list.viewport(),
        )

    def check_all_json_regions(self):
        for index in range(self.region_list.count()):
            item = self.region_list.item(index)
            if item.checkState() != Qt.Checked:
                item.setCheckState(Qt.Checked)
            item.setSelected(True)

    def checked_json_region_names(self):
        return [
            self.region_list.item(index).text()
            for index in range(self.region_list.count())
            if self.region_list.item(index).checkState() == Qt.Checked
        ]

    def selected_or_checked_json_region_names(self):
        checked_names = self.checked_json_region_names()
        if checked_names:
            return checked_names
        return [item.text() for item in self.region_list.selectedItems()]

    def _latest_json_region_name(self):
        if (
            self.last_json_region_name
            and self.last_json_region_name in self.canvas.model.json_regions
        ):
            return self.last_json_region_name
        if self.canvas.model.json_regions:
            return next(reversed(self.canvas.model.json_regions))
        return None

    def _focus_and_select_json_name(self):
        if not self.is_editing_json or self.edit_region_name.isHidden():
            return
        self.edit_region_name.setFocus(Qt.ShortcutFocusReason)
        self.edit_region_name.selectAll()

    def new_json_region(self):
        self.start_edit_json_region(None)

    def _mark_center_offset_edited(self, axis):
        if self._loading_center_offsets:
            return
        if axis == "x":
            self._center_dx_edited = True
        else:
            self._center_dy_edited = True

    def _set_center_offset_controls(self, dx, dy):
        self._loading_center_offsets = True
        self.center_dx_spin.setValue(dx)
        self.center_dy_spin.setValue(dy)
        self._loading_center_offsets = False
        self._center_dx_edited = False
        self._center_dy_edited = False

    def _mark_json_scale_edited(self, axis):
        if self._loading_json_scales:
            return
        if axis == "h":
            self._hscale_edited = True
        else:
            self._vscale_edited = True

    def _set_json_scale_controls(self, hscale, vscale):
        self._loading_json_scales = True
        self.hscale_spin.setValue(hscale)
        self.vscale_spin.setValue(vscale)
        self._loading_json_scales = False
        self._hscale_edited = False
        self._vscale_edited = False

    def start_edit_json_region(self, name):
        self.is_editing_json = True
        self.editing_json_original_name = name
        self.edit_region_name.setVisible(True)
        self.center_offset_group.setVisible(True)
        self.json_scale_group.setVisible(True)
        self.btn_cancel.setVisible(True)
        if name:
            self.last_json_region_name = name
            self.edit_region_name.setText(name)
            rect = self.canvas.model.json_regions[name]
            self.canvas.model.selection_rect = QRect(rect)
            self.set_tool(ToolType.SELECT)
            self.canvas.fit_to_rect(rect)
            self.update_selection_ui()
            center_offset = self.canvas.model.json_region_centers.get(
                name, QPointF(0, 0)
            )
            display_center_dy = (
                -center_offset.y()
                if self.canvas.model.coordinate_mode.y_down
                else center_offset.y()
            )
            self._set_center_offset_controls(
                center_offset.x(), display_center_dy
            )
            scale = self.canvas.model.json_region_scales.get(
                name, QPointF(1, 1)
            )
            self._set_json_scale_controls(scale.x(), scale.y())
            self.mipmap_checkbox.setChecked(
                self.canvas.model.json_region_mipmaps.get(name, False)
            )
        else:
            latest_name = self._latest_json_region_name()
            self.edit_region_name.setText(latest_name or "untitled")
            if not self.canvas.model.selection_rect:
                if self.canvas.model.coordinate_mode.y_down:
                    self.canvas.model.selection_rect = QRect(0, -32, 32, 32)
                else:
                    self.canvas.model.selection_rect = QRect(0, 0, 32, 32)
            self.set_tool(ToolType.SELECT)
            self.update_selection_ui()
            if latest_name:
                center_offset = self.canvas.model.json_region_centers.get(
                    latest_name, QPointF(0, 0)
                )
                display_center_dy = (
                    -center_offset.y()
                    if self.canvas.model.coordinate_mode.y_down
                    else center_offset.y()
                )
                self._set_center_offset_controls(
                    center_offset.x(), display_center_dy
                )
                scale = self.canvas.model.json_region_scales.get(
                    latest_name, QPointF(1, 1)
                )
                self._set_json_scale_controls(scale.x(), scale.y())
            else:
                self._set_center_offset_controls(0.0, 0.0)
                self._set_json_scale_controls(1.0, 1.0)
            self.mipmap_checkbox.setChecked(False)
        self.btn_action.setText("保存 JSON 切片 (Enter)")
        self.btn_action.setStyleSheet(
            "background-color: #27ae60; color: white; font-weight: bold;"
        )
        QTimer.singleShot(0, self._focus_and_select_json_name)

    def exit_edit_json_mode(self):
        self.is_editing_json = False
        self.editing_json_original_name = None
        self.edit_region_name.setVisible(False)
        self.center_offset_group.setVisible(False)
        self.json_scale_group.setVisible(False)
        self.btn_cancel.setVisible(False)
        self.btn_action.setText("✂ 裁剪并保存选区")
        self.btn_action.setStyleSheet(
            "background-color: #2c3e50; color: white; font-weight: bold;"
        )
        self.canvas.update()

    def on_btn_action_clicked(self):
        if self.is_editing_json:
            self.save_json_region()
        else:
            self.crop_and_export()

    def save_json_region(self):
        new_name = self.edit_region_name.text().strip()
        if not new_name:
            QMessageBox.warning(self, "错误", "纹理名不能为空")
            return False
        rect = self.canvas.model.selection_rect
        if not rect:
            QMessageBox.warning(self, "错误", "请先框选一个区域")
            return False

        self.canvas.model.push_undo_state()
        old_name = self.editing_json_original_name
        stored_center = self.canvas.model.json_region_centers.get(
            old_name, QPointF(0, 0)
        )
        stored_scale = self.canvas.model.json_region_scales.get(
            old_name, QPointF(1, 1)
        )
        display_center_dy = self.center_dy_spin.value()
        edited_world_center_dy = (
            -display_center_dy if self.canvas.model.coordinate_mode.y_down
            else display_center_dy
        )
        center_dx = (
            stored_center.x()
            if old_name and not self._center_dx_edited
            else self.center_dx_spin.value()
        )
        center_dy = (
            stored_center.y()
            if old_name and not self._center_dy_edited
            else edited_world_center_dy
        )
        center_offset = QPointF(center_dx, center_dy)
        hscale = (
            stored_scale.x()
            if old_name and not self._hscale_edited
            else self.hscale_spin.value()
        )
        vscale = (
            stored_scale.y()
            if old_name and not self._vscale_edited
            else self.vscale_spin.value()
        )
        scale = QPointF(hscale, vscale)
        mipmap = self.mipmap_checkbox.isChecked()
        if old_name and old_name != new_name:
            self.canvas.model.json_regions.pop(old_name, None)
            self.canvas.model.json_region_centers.pop(old_name, None)
            self.canvas.model.json_region_scales.pop(old_name, None)
            self.canvas.model.json_region_mipmaps.pop(old_name, None)
        self.canvas.model.json_regions[new_name] = QRect(rect)
        self.canvas.model.json_region_centers[new_name] = QPointF(center_offset)
        self.canvas.model.json_region_scales[new_name] = QPointF(scale)
        self.canvas.model.json_region_mipmaps[new_name] = mipmap
        self.last_json_region_name = new_name
        self.refresh_region_list()
        self.exit_edit_json_mode()
        return True

    def delete_json_regions(self, names):
        names = list(dict.fromkeys(
            name for name in names if name in self.canvas.model.json_regions
        ))
        if not names:
            return False

        self.canvas.model.push_undo_state()
        for name in names:
            del self.canvas.model.json_regions[name]
            self.canvas.model.json_region_centers.pop(name, None)
            self.canvas.model.json_region_scales.pop(name, None)
            self.canvas.model.json_region_mipmaps.pop(name, None)

        if self.last_json_region_name in names:
            self.last_json_region_name = self._latest_json_region_name()
        if self.editing_json_original_name in names:
            self.exit_edit_json_mode()
        self.refresh_region_list()
        return True

    def delete_json_region(self, name):
        return self.delete_json_regions([name])

    def delete_selected_json_regions(self):
        names = self.selected_or_checked_json_region_names()
        if not names:
            item = self.region_list.currentItem()
            if item:
                names = [item.text()]
        if self.delete_json_regions(names):
            self.statusBar().showMessage(
                f"已删除 {len(names)} 个 JSON 切片（画布像素未修改）", 2500
            )

    def delete_json_regions_for_selection(self):
        selection = self.canvas.model.selection_rect
        if not selection or selection.isEmpty():
            self.statusBar().showMessage(
                "Ctrl+Del 已触发：当前没有选区", 3500
            )
            return False

        selection = QRect(selection).normalized()
        intersecting = []
        partial_names = []
        for name, rect in self.canvas.model.json_regions.items():
            region_rect = QRect(rect).normalized()
            if not selection.intersects(region_rect):
                continue
            intersecting.append(name)
            if not selection.contains(region_rect):
                partial_names.append(name)

        if partial_names:
            preview = "、".join(partial_names[:3])
            if len(partial_names) > 3:
                preview += f" 等 {len(partial_names)} 个"
            self.statusBar().showMessage(
                f"未删除：选区未完整包含切片 {preview}", 4500
            )
            return False

        if not intersecting:
            self.statusBar().showMessage(
                "Ctrl+Del 已触发：选区内没有 JSON 切片", 3500
            )
            return False

        names = intersecting
        if self.delete_json_regions(names):
            self.statusBar().showMessage(
                f"已删除选区内 {len(names)} 个完整 JSON 切片（画布像素未修改）",
                3500,
            )
            return True
        return False

    def trigger_ctrl_delete(self):
        if self._ctrl_delete_consumed:
            return
        self._ctrl_delete_consumed = True
        QTimer.singleShot(1000, self.reset_ctrl_delete_guard)
        self.delete_json_regions_for_selection()

    def reset_ctrl_delete_guard(self):
        self._ctrl_delete_consumed = False

    def delete_current_context(self):
        if self.is_editing_json:
            name = self.editing_json_original_name
            if name:
                self.delete_json_region(name)
                self.exit_edit_json_mode()
            return
        focus_widget = QApplication.focusWidget()
        list_has_focus = (
            focus_widget is self.region_list
            or (
                focus_widget is not None
                and self.region_list.isAncestorOf(focus_widget)
            )
        )
        if list_has_focus:
            self.delete_selected_json_regions()
            return
        self.canvas.delete_selection()

    def edit_selected_json_region(self):
        item = self.region_list.currentItem()
        if item and item.text() in self.canvas.model.json_regions:
            self.start_edit_json_region(item.text())

    def copy_json_region(self, name):
        if name in self.canvas.model.json_regions:
            self.json_clipboard_rect = QRect(
                self.canvas.model.json_regions[name]
            )
            self.json_clipboard_name = name
            self.json_clipboard_center = QPointF(
                self.canvas.model.json_region_centers.get(name, QPointF(0, 0))
            )
            self.json_clipboard_scale = QPointF(
                self.canvas.model.json_region_scales.get(name, QPointF(1, 1))
            )
            self.json_clipboard_mipmap = self.canvas.model.json_region_mipmaps.get(
                name, False
            )

    def paste_json_region(self):
        if not self.json_clipboard_rect:
            return
        base_name = (self.json_clipboard_name or "pasted") + "_copy"
        new_name = base_name
        index = 2
        while new_name in self.canvas.model.json_regions:
            new_name = f"{base_name}{index}"
            index += 1
        self.canvas.model.push_undo_state()
        self.canvas.model.json_regions[new_name] = QRect(
            self.json_clipboard_rect
        )
        self.canvas.model.json_region_centers[new_name] = QPointF(
            self.json_clipboard_center or QPointF(0, 0)
        )
        self.canvas.model.json_region_scales[new_name] = QPointF(
            self.json_clipboard_scale or QPointF(1, 1)
        )
        self.canvas.model.json_region_mipmaps[new_name] = bool(
            self.json_clipboard_mipmap
        )
        self.last_json_region_name = new_name
        self.refresh_region_list()

    # ------------------------------------------------------------------
    # Toolbar and menus
    # ------------------------------------------------------------------
    def create_toolbar(self):
        toolbar = QToolBar("Tools", self)
        self.addToolBar(Qt.LeftToolBarArea, toolbar)
        toolbar.setMovable(False)
        group = QActionGroup(self)

        def add_tool(name, tool_enum, checked=False):
            action = QAction(name, self)
            action.setCheckable(True)
            action.setChecked(checked)
            action.triggered.connect(lambda: self.set_tool(tool_enum))
            group.addAction(action)
            toolbar.addAction(action)
            self.action_map[tool_enum] = action
            return action

        add_tool("画笔 (P)", ToolType.PEN, True).setShortcut("P")
        add_tool("橡皮 (E)", ToolType.ERASER).setShortcut("E")
        add_tool("选择 (S)", ToolType.SELECT).setShortcut("S")
        add_tool("顶点 (V)", ToolType.POINT).setShortcut("V")

    def set_tool(self, tool):
        self.canvas.current_tool = tool
        if tool in self.action_map:
            self.action_map[tool].setChecked(True)
        self.canvas.refresh_selected_pixel_ui()
        self.canvas.update()

    def create_shortcuts(self):
        # Window-wide Return/Enter handling lets users adjust the selection on
        # the canvas and then save without having to focus the name field again.
        self.save_json_return_shortcut = QShortcut(
            QKeySequence(Qt.Key_Return), self
        )
        self.save_json_return_shortcut.setContext(Qt.WindowShortcut)
        self.save_json_return_shortcut.activated.connect(
            self.save_json_region_from_shortcut
        )

        self.save_json_enter_shortcut = QShortcut(
            QKeySequence(Qt.Key_Enter), self
        )
        self.save_json_enter_shortcut.setContext(Qt.WindowShortcut)
        self.save_json_enter_shortcut.activated.connect(
            self.save_json_region_from_shortcut
        )

        self.edit_json_f2_shortcut = QShortcut(
            QKeySequence(Qt.Key_F2), self.region_list
        )
        self.edit_json_f2_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self.edit_json_f2_shortcut.activated.connect(
            self.edit_selected_json_region
        )

        self.delete_matching_json_shortcut = QShortcut(
            QKeySequence("Ctrl+Del"), self
        )
        self.delete_matching_json_shortcut.setContext(Qt.ApplicationShortcut)
        self.delete_matching_json_shortcut.setAutoRepeat(False)
        self.delete_matching_json_shortcut.activated.connect(
            self.trigger_ctrl_delete
        )
        self.delete_matching_json_shortcut.activatedAmbiguously.connect(
            self.trigger_ctrl_delete
        )

    def save_json_region_from_shortcut(self):
        if self.is_editing_json:
            self.save_json_region()

    def create_menu(self):
        menu_bar = self.menuBar()
        menu_bar.clear()

        file_menu = menu_bar.addMenu("文件")
        file_menu.addAction("导入图片...", self.import_img, "Ctrl+O")
        self.action_new_json_region = file_menu.addAction(
            "新建 JSON 切片", self.new_json_region, "Ctrl+J"
        )
        file_menu.addAction("导入 JSON...", self.import_json, "Ctrl+Shift+J")
        file_menu.addSeparator()
        file_menu.addAction("导出画布...", self.export_img, "Ctrl+S")
        file_menu.addAction(
            "导出 JSON...", self.export_json, "Ctrl+Shift+S"
        )

        edit_menu = menu_bar.addMenu("编辑")
        edit_menu.addAction("撤销", self.do_undo, "Ctrl+Z")
        edit_menu.addAction("重做", self.do_redo, "Ctrl+Y")
        edit_menu.addSeparator()
        edit_menu.addAction(
            "复制", lambda: self.canvas.copy_action(), "Ctrl+C"
        )
        edit_menu.addAction(
            "剪切", lambda: self.canvas.cut_action(), "Ctrl+X"
        )
        edit_menu.addAction(
            "粘贴", lambda: self.canvas.paste_action(), "Ctrl+V"
        )
        edit_menu.addSeparator()
        edit_menu.addAction(
            "顺时针旋转 90°",
            lambda: self.canvas.rotate_action(True),
            "Ctrl+R",
        )
        edit_menu.addAction(
            "逆时针旋转 90°",
            lambda: self.canvas.rotate_action(False),
            "Ctrl+Shift+R",
        )
        edit_menu.addAction(
            "左右翻转", lambda: self.canvas.flip_action(True)
        )
        edit_menu.addAction(
            "上下翻转", lambda: self.canvas.flip_action(False)
        )
        edit_menu.addSeparator()
        edit_menu.addAction("删除选区", self.canvas.delete_selection)
        edit_menu.addAction(
            "裁剪选区并另存...", self.crop_and_export, "Ctrl+Shift+C"
        )
        edit_menu.addAction("清空画布", self.do_clear)
        settings_menu = menu_bar.addMenu("设置")
        coordinate_menu = settings_menu.addMenu("坐标系 / JSON 坐标")
        coordinate_actions = QActionGroup(self)
        coordinate_actions.setExclusive(True)
        self.action_coordinate_top_left = coordinate_menu.addAction(
            "左上角原点，Y 向下"
        )
        self.action_coordinate_bottom_left = coordinate_menu.addAction(
            "左下角原点，Y 向上"
        )
        for action in [
            self.action_coordinate_top_left,
            self.action_coordinate_bottom_left,
        ]:
            action.setCheckable(True)
            coordinate_actions.addAction(action)
        self.action_coordinate_top_left.triggered.connect(
            lambda: self.set_coordinate_mode(CoordinateMode.TOP_LEFT_Y_DOWN)
        )
        self.action_coordinate_bottom_left.triggered.connect(
            lambda: self.set_coordinate_mode(CoordinateMode.BOTTOM_LEFT_Y_UP)
        )

    # ------------------------------------------------------------------
    # Commands and file I/O
    # ------------------------------------------------------------------
    def do_undo(self):
        if self.canvas.model.undo():
            self.refresh_region_list()
            self.update_selection_ui()
            self.exit_edit_json_mode()
            self.canvas.update()

    def do_redo(self):
        if self.canvas.model.redo():
            self.refresh_region_list()
            self.update_selection_ui()
            self.exit_edit_json_mode()
            self.canvas.update()

    def do_clear(self):
        self.canvas.model.clear_canvas()
        self.last_json_region_name = None
        self.opened_image_paths = []
        self.opened_json_paths = []
        self.last_opened_directory = None
        self.refresh_region_list()
        self.update_selection_ui()
        self.exit_edit_json_mode()
        self.canvas.update()

    def import_img(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入图片",
            "",
            "支持的图片 (*.png *.jpg *.jpeg *.bmp);;PNG 图片 (*.png);;JPEG 图片 (*.jpg *.jpeg);;BMP 图片 (*.bmp)",
        )
        if path:
            self._import_image_paths([path])

    def _import_image_paths(self, paths, placement_anchor=None):
        """Import image files through the same path used by the File menu."""
        imported_count = 0
        unreadable_paths = []
        imported_paths = []
        next_x = placement_anchor.x() if placement_anchor is not None else None
        anchor_y = placement_anchor.y() if placement_anchor is not None else None

        for path in paths:
            image = QImage(path).convertToFormat(
                QImage.Format_ARGB32_Premultiplied
            )
            if image.isNull():
                unreadable_paths.append(path)
                continue

            if placement_anchor is not None:
                self.canvas.model.place_image_at(
                    image, QPoint(int(next_x), int(anchor_y))
                )
                next_x += image.width()
            elif self.canvas.model.is_canvas_empty():
                self.canvas.model.load_image(image)
            else:
                self.canvas.model.append_image_right(image)
            imported_count += 1
            imported_paths.append(os.path.abspath(path))

        if unreadable_paths:
            names = "\n".join(unreadable_paths)
            QMessageBox.warning(self, "错误", f"无法读取以下图片：\n{names}")

        if not imported_count:
            return 0

        self.opened_image_paths.extend(imported_paths)
        if self.last_opened_directory is None:
            self.last_opened_directory = os.path.dirname(imported_paths[0])

        self.set_tool(ToolType.SELECT)
        self.refresh_region_list()
        self.exit_edit_json_mode()
        if self.canvas.model.selection_rect:
            self.canvas.fit_to_rect(self.canvas.model.selection_rect)
        self.update_selection_ui()
        return imported_count

    @staticmethod
    def _split_supported_paths(paths):
        image_paths = []
        json_paths = []
        for path in paths:
            path = str(path)
            lower_path = path.lower()
            if lower_path.endswith((".png", ".jpg", ".jpeg", ".bmp")):
                image_paths.append(path)
            elif path.lower().endswith(".json"):
                json_paths.append(path)
        return image_paths, json_paths

    @classmethod
    def _drop_paths_from_mime_data(cls, mime_data):
        if not mime_data.hasUrls():
            return [], []

        local_paths = [
            url.toLocalFile() for url in mime_data.urls() if url.isLocalFile()
        ]
        return cls._split_supported_paths(local_paths)

    def open_external_paths(self, paths, source="外部文件"):
        """Open images and JSON supplied by the command line or shell."""
        image_paths, json_paths = self._split_supported_paths(paths)
        image_count = self._import_image_paths(image_paths) if image_paths else 0
        json_count = self._import_json_paths(json_paths) if json_paths else 0

        status_parts = []
        if image_count:
            status_parts.append(f"{image_count} 个图片")
        if json_count:
            status_parts.append(f"{json_count} 个 JSON")
        if status_parts:
            self.statusBar().showMessage(
                f"已通过{source}导入 {'、'.join(status_parts)}", 3000
            )
        return image_count, json_count

    def dragEnterEvent(self, event):
        image_paths, json_paths = self._drop_paths_from_mime_data(event.mimeData())
        if image_paths or json_paths:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        image_paths, json_paths = self._drop_paths_from_mime_data(event.mimeData())
        if image_paths or json_paths:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        image_paths, json_paths = self._drop_paths_from_mime_data(event.mimeData())
        if not image_paths and not json_paths:
            event.ignore()
            return

        event.acceptProposedAction()
        status_parts = []
        selection = self.canvas.model.selection_rect
        placement_anchor = (
            QPoint(selection.x(), selection.y()) if selection else None
        )
        image_count = (
            self._import_image_paths(image_paths, placement_anchor)
            if image_paths
            else 0
        )
        json_count = self._import_json_paths(json_paths) if json_paths else 0
        if image_count:
            status_parts.append(f"{image_count} 个图片")
        if json_count:
            status_parts.append(f"{json_count} 个 JSON")
        if status_parts:
            self.statusBar().showMessage(
                f"已通过拖拽导入 {'、'.join(status_parts)}", 2500
            )

    def import_json(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入 JSON", "", "JSON Files (*.json)"
        )
        if path:
            self._import_json_paths([path])

    def _import_json_paths(self, paths):
        """Import one or more JSON region files through one shared code path."""
        merged_regions = {}
        used_names = set(self.canvas.model.json_regions)
        duplicate_names = []
        duplicate_entries = []
        imported_count = 0
        imported_paths = []
        errors = []
        for path in paths:
            try:
                with open(path, "r", encoding="utf-8") as file:
                    data = json.load(file)
                if not isinstance(data, dict):
                    raise ValueError("JSON 根节点必须是对象")
                for raw_name, region in data.items():
                    region_name = str(raw_name)
                    if region_name in used_names:
                        duplicate_names.append(region_name)
                        duplicate_entries.append((region_name, region))
                        continue
                    used_names.add(region_name)
                    merged_regions[region_name] = region
                imported_count += 1
                imported_paths.append(os.path.abspath(path))
            except (OSError, ValueError, json.JSONDecodeError) as error:
                errors.append(f"{path}\n{error}")

        if duplicate_names:
            duplicate_text = "\n".join(
                f"• {name}" for name in dict.fromkeys(duplicate_names)
            )
            message = (
                "检测到以下同名 JSON 切片：\n\n"
                f"{duplicate_text}\n\n"
                "是否为重名切片自动添加 _2、_3 等后缀后继续导入？\n"
                "选择“否”将取消本次全部导入。"
            )
            if errors:
                message += "\n\n同时发现以下读取错误：\n" + "\n\n".join(errors)
            answer = QMessageBox.question(
                self,
                "发现同名 JSON 切片",
                message,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return 0
            for base_name, region in duplicate_entries:
                suffix = 2
                unique_name = f"{base_name}_{suffix}"
                while unique_name in used_names:
                    suffix += 1
                    unique_name = f"{base_name}_{suffix}"
                used_names.add(unique_name)
                merged_regions[unique_name] = region

        if imported_count:
            imported_names = self.canvas.model.load_json_regions(
                merged_regions, merge=True
            )
            if not self.opened_json_paths and imported_paths:
                self.opened_json_paths = [imported_paths[0]]
            if self.last_opened_directory is None:
                self.last_opened_directory = os.path.dirname(imported_paths[0])
            if imported_names:
                self.last_json_region_name = imported_names[-1]
            self.refresh_region_list()

        if errors:
            QMessageBox.warning(
                self,
                "JSON 导入失败",
                "\n\n".join(errors),
            )
        return imported_count

    def _default_save_path(self, filename):
        if self.last_opened_directory:
            return os.path.join(self.last_opened_directory, filename)
        return filename

    def _default_json_export_path(self):
        if len(self.opened_json_paths) == 1:
            return self._default_save_path(
                os.path.basename(self.opened_json_paths[0])
            )
        if not self.opened_json_paths and len(self.opened_image_paths) == 1:
            image_path = self.opened_image_paths[0]
            filename = os.path.splitext(os.path.basename(image_path))[0] + ".json"
            return self._default_save_path(filename)
        return self._default_save_path("sprites.json")

    def _default_image_export_path(self):
        if len(self.opened_image_paths) == 1:
            image_path = self.opened_image_paths[0]
            filename = os.path.splitext(os.path.basename(image_path))[0] + ".png"
            return self._default_save_path(filename)
        return self._default_save_path("tex.png")

    def export_json(self):
        if self.is_editing_json and not self.save_json_region():
            return
        if not self.canvas.model.json_regions:
            QMessageBox.warning(self, "无法导出", "当前没有可导出的 JSON 切片")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 JSON",
            self._default_json_export_path(),
            "JSON Files (*.json)",
        )
        if not path:
            return
        try:
            export_data = self.canvas.model.export_json_regions()
            with open(path, "w", encoding="utf-8") as file:
                json.dump(export_data, file, indent=2, ensure_ascii=False)
        except OSError as error:
            QMessageBox.warning(self, "错误", str(error))

    def on_region_selected(self, item):
        name = item.text()
        if name in self.canvas.model.json_regions:
            self.last_json_region_name = name
            rect = QRect(self.canvas.model.json_regions[name])
            self.canvas.model.selection_rect = rect
            self.canvas.fit_to_rect(rect)
            self.update_selection_ui()

    def export_img(self):
        dialog = ExportDialog(
            self, self.canvas.model.selection_rect is not None
        )
        if dialog.exec_() != QDialog.Accepted:
            return
        rect = (
            self.canvas.model.selection_rect
            if dialog.should_export_selection()
            else self.canvas.get_content_rect()
        )
        image = self.canvas.get_image(rect)
        if image.isNull():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "保存画布", self._default_image_export_path(), "PNG (*.png)"
        )
        if path and not image.save(path):
            QMessageBox.warning(self, "错误", "保存图片失败")

    def crop_and_export(self):
        rect = self.canvas.model.selection_rect
        if not rect:
            return
        image = self.canvas.get_image(rect)
        if image.isNull():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "保存裁剪", self._default_save_path("crop.png"), "PNG (*.png)"
        )
        if path and not image.save(path):
            QMessageBox.warning(self, "错误", "保存图片失败")

    def set_current_color(self, color):
        if not color.isValid():
            return
        self.canvas.current_color = QColor(color)
        self.refresh_current_color_ui()

    def refresh_current_color_ui(self):
        color = self.canvas.current_color
        luminance = (
            color.red() * 299 + color.green() * 587 + color.blue() * 114
        ) / 1000
        text_color = "#111" if luminance >= 150 and color.alpha() >= 128 else "#fff"
        self.current_color_button.setText(
            f"ARGB: ({color.alpha()},{color.red()},"
            f"{color.green()},{color.blue()}) · 点击自定义"
        )
        self.current_color_button.setStyleSheet(
            f"background-color: rgba({color.red()}, {color.green()}, "
            f"{color.blue()}, {color.alpha()}); color: {text_color}; "
            "font-weight: bold; border: 1px solid #666; border-radius: 4px;"
        )

    def pick_color(self):
        color = QColorDialog.getColor(
            self.canvas.current_color,
            self,
            "选择画笔颜色",
            QColorDialog.ShowAlphaChannel,
        )
        if color.isValid():
            self.set_current_color(color)
