import json
from PyQt5.QtWidgets import (QMainWindow, QAction, QFileDialog, QColorDialog, 
                             QLabel, QToolBar, QActionGroup, QDialog,
                             QDockWidget, QWidget, QVBoxLayout, QGridLayout, 
                             QPushButton, QMessageBox, QListWidget,
                             QSpinBox, QGroupBox, QMenu, QLineEdit)
from PyQt5.QtGui import QImage
from PyQt5.QtCore import Qt, QRect, QPoint

from consts import ToolType
from canvas import TextureCanvas
from dialogs import ExportDialog

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PiexlEditor ver 7.0 by phsonh")
        self.resize(1300, 800)
        
        self.canvas = TextureCanvas(self)
        self.setCentralWidget(self.canvas)
        
        self.status_lbl = QLabel()
        self.statusBar().addPermanentWidget(self.status_lbl)
        
        self.is_editing_json = False
        self.editing_json_original_name = None
        self.json_clipboard_rect = None
        self.json_clipboard_name = None
        
        self.create_property_panel()
        
        self.action_map = {}
        self.create_toolbar()
        self.create_menu()

    def create_property_panel(self):
        dock = QDockWidget("属性/裁剪控制", self)
        dock.setAllowedAreas(Qt.RightDockWidgetArea)
        panel = QWidget()
        panel.setMinimumWidth(320) 
        
        layout = QVBoxLayout(panel)
        
        def make_sb():
            sb = QSpinBox()
            sb.setRange(-99999, 99999) 
            return sb
            
        self.edit_l = make_sb(); self.edit_r = make_sb()
        self.edit_b = make_sb(); self.edit_t = make_sb()
        
        self.tl_x = make_sb(); self.tl_y = make_sb()
        self.tr_x = make_sb(); self.tr_y = make_sb()
        self.bl_x = make_sb(); self.bl_y = make_sb()
        self.br_x = make_sb(); self.br_y = make_sb()
        
        self._updating_ui = False 
        
        group_edges = QGroupBox("边界坐标 (同步)")
        grid_edges = QGridLayout(group_edges)
        grid_edges.addWidget(QLabel("左边界 (L):"), 0, 0); grid_edges.addWidget(self.edit_l, 0, 1)
        grid_edges.addWidget(QLabel("右边界 (R):"), 1, 0); grid_edges.addWidget(self.edit_r, 1, 1)
        grid_edges.addWidget(QLabel("下边界 (B):"), 2, 0); grid_edges.addWidget(self.edit_b, 2, 1)
        grid_edges.addWidget(QLabel("上边界 (T):"), 3, 0); grid_edges.addWidget(self.edit_t, 3, 1)
        layout.addWidget(group_edges)
        
        group_corners = QGroupBox("角点坐标 (X, Y) (对角线同步)")
        grid_corners = QGridLayout(group_corners)
        grid_corners.addWidget(QLabel("左上 (TL):"), 0, 0); grid_corners.addWidget(self.tl_x, 0, 1); grid_corners.addWidget(self.tl_y, 0, 2)
        grid_corners.addWidget(QLabel("右上 (TR):"), 1, 0); grid_corners.addWidget(self.tr_x, 1, 1); grid_corners.addWidget(self.tr_y, 1, 2)
        grid_corners.addWidget(QLabel("左下 (BL):"), 2, 0); grid_corners.addWidget(self.bl_x, 2, 1); grid_corners.addWidget(self.bl_y, 2, 2)
        grid_corners.addWidget(QLabel("右下 (BR):"), 3, 0); grid_corners.addWidget(self.br_x, 3, 1); grid_corners.addWidget(self.br_y, 3, 2)
        layout.addWidget(group_corners)
        
        def bind(widgets, edge):
            for w in widgets:
                w.valueChanged.connect(lambda val, e=edge: self.on_edge_changed(e, val))
                
        bind([self.edit_l, self.tl_x, self.bl_x], 'left')
        bind([self.edit_r, self.tr_x, self.br_x], 'right')
        bind([self.edit_b, self.bl_y, self.br_y], 'bottom')
        bind([self.edit_t, self.tl_y, self.tr_y], 'top')
        
        layout.addSpacing(10)
        
        self.edit_region_name = QLineEdit()
        self.edit_region_name.setPlaceholderText("在此输入纹理名称...")
        self.edit_region_name.setVisible(False)
        layout.addWidget(self.edit_region_name)
        
        self.btn_action = QPushButton("裁剪并保存选区")
        self.btn_action.setFixedHeight(45)
        self.btn_action.setStyleSheet("background-color: #2c3e50; color: white; font-weight: bold;")
        self.btn_action.clicked.connect(self.on_btn_action_clicked)
        layout.addWidget(self.btn_action)

        # --- 新增: 放弃/退出编辑按钮 ---
        self.btn_cancel = QPushButton("放弃修改并退出")
        self.btn_cancel.setFixedHeight(30)
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self.exit_edit_json_mode)
        layout.addWidget(self.btn_cancel)
        
        layout.addSpacing(10)
        
        layout.addWidget(QLabel("JSON 切片区域 (右键可操作):"))
        self.region_list = QListWidget()
        self.region_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.region_list.customContextMenuRequested.connect(self.show_list_context_menu)
        self.region_list.itemClicked.connect(self.on_region_selected)
        layout.addWidget(self.region_list)
        
        layout.addStretch()
        dock.setWidget(panel)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    def on_edge_changed(self, edge, val):
        if self._updating_ui: return
        self._updating_ui = True
        
        if edge == 'left':
            for w in[self.edit_l, self.tl_x, self.bl_x]: w.setValue(val)
        elif edge == 'right':
            for w in[self.edit_r, self.tr_x, self.br_x]: w.setValue(val)
        elif edge == 'bottom':
            for w in[self.edit_b, self.bl_y, self.br_y]: w.setValue(val)
        elif edge == 'top':
            for w in[self.edit_t, self.tl_y, self.tr_y]: w.setValue(val)
            
        self._updating_ui = False
        self.apply_inputs_to_selection()

    def apply_inputs_to_selection(self):
        if self._updating_ui: return
        l = self.edit_l.value(); r = self.edit_r.value()
        b = self.edit_b.value(); t = self.edit_t.value()
        x = min(l, r); y = min(b, t)
        w = max(1, abs(r - l)); h = max(1, abs(t - b))
        new_rect = QRect(x, y, w, h)
        self.canvas.model.selection_rect = new_rect
        self.canvas.update()

    def update_mouse_status(self, x, y, z):
        self.status_lbl.setText(f"Pos: ({x}, {y}) | Zoom: {z:.1f}")

    def update_selection_ui(self):
        rect = self.canvas.model.selection_rect
        self._updating_ui = True
        if rect:
            l = rect.x(); r = rect.x() + rect.width()
            b = rect.y(); t = rect.y() + rect.height()
        else:
            l = r = b = t = 0
        for w in[self.edit_l, self.tl_x, self.bl_x]: w.setValue(l)
        for w in[self.edit_r, self.tr_x, self.br_x]: w.setValue(r)
        for w in[self.edit_b, self.bl_y, self.br_y]: w.setValue(b)
        for w in [self.edit_t, self.tl_y, self.tr_y]: w.setValue(t)
        self._updating_ui = False

    def show_list_context_menu(self, pos):
        item = self.region_list.itemAt(pos)
        menu = QMenu(self)
        if item:
            action_mod = menu.addAction("修改")
            action_del = menu.addAction("删除")
            action_copy = menu.addAction("复制")
            menu.addSeparator()
        action_new = menu.addAction("新建")
        action_paste = menu.addAction("粘贴")
        action_paste.setEnabled(self.json_clipboard_rect is not None)
        menu.addSeparator()
        action_export = menu.addAction("导出 JSON...")
        action = menu.exec_(self.region_list.mapToGlobal(pos))
        if item:
            name = item.text()
            if action == action_mod: self.start_edit_json_region(name)
            elif action == action_del: self.delete_json_region(name)
            elif action == action_copy: self.copy_json_region(name)
        if action == action_new: self.start_edit_json_region(None)
        elif action == action_paste: self.paste_json_region()
        elif action == action_export: self.export_json()

    def refresh_region_list(self):
        self.region_list.clear()
        for name in self.canvas.model.json_regions.keys():
            self.region_list.addItem(name)
        self.canvas.update()

    def start_edit_json_region(self, name):
        self.is_editing_json = True
        self.editing_json_original_name = name
        self.edit_region_name.setVisible(True)
        self.btn_cancel.setVisible(True) # 显示取消按钮
        if name:
            self.edit_region_name.setText(name)
            rect = self.canvas.model.json_regions[name]
            self.canvas.model.selection_rect = rect
            self.set_tool(ToolType.SELECT)
            self.canvas.fit_to_rect(rect)
            self.update_selection_ui()
        else:
            self.edit_region_name.setText("new_region")
            if not self.canvas.model.selection_rect:
                self.canvas.model.selection_rect = QRect(0, 0, 32, 32)
            self.set_tool(ToolType.SELECT)
            self.update_selection_ui()
        self.btn_action.setText("保存 JSON 切片")
        self.btn_action.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold;")

    def exit_edit_json_mode(self):
        self.is_editing_json = False
        self.editing_json_original_name = None
        self.edit_region_name.setVisible(False)
        self.btn_cancel.setVisible(False) # 隐藏取消按钮
        self.btn_action.setText("✂ 裁剪并保存选区")
        self.btn_action.setStyleSheet("background-color: #2c3e50; color: white; font-weight: bold;")
        self.canvas.update()

    def on_btn_action_clicked(self):
        if self.is_editing_json: self.save_json_region()
        else: self.crop_and_export()

    def save_json_region(self):
        new_name = self.edit_region_name.text().strip()
        if not new_name: QMessageBox.warning(self, "错误", "纹理名不能为空"); return
        rect = self.canvas.model.selection_rect
        if not rect: QMessageBox.warning(self, "错误", "请先框选一个区域"); return
        if self.editing_json_original_name and self.editing_json_original_name != new_name:
            if self.editing_json_original_name in self.canvas.model.json_regions:
                del self.canvas.model.json_regions[self.editing_json_original_name]
        self.canvas.model.json_regions[new_name] = QRect(rect)
        self.refresh_region_list()
        self.exit_edit_json_mode()

    def delete_json_region(self, name):
        if name in self.canvas.model.json_regions:
            del self.canvas.model.json_regions[name]
            self.refresh_region_list()

    def copy_json_region(self, name):
        if name in self.canvas.model.json_regions:
            self.json_clipboard_rect = QRect(self.canvas.model.json_regions[name])
            self.json_clipboard_name = name

    def paste_json_region(self):
        if not self.json_clipboard_rect: return
        new_name = (self.json_clipboard_name or "pasted") + "_copy"
        self.canvas.model.json_regions[new_name] = QRect(self.json_clipboard_rect)
        self.refresh_region_list()

    def create_toolbar(self):
        tb = QToolBar("Tools", self); self.addToolBar(Qt.LeftToolBarArea, tb)
        tb.setMovable(False); grp = QActionGroup(self)
        def add_tool(name, tool_enum, checked=False):
            action = QAction(name, self); action.setCheckable(True)
            action.setChecked(checked); action.triggered.connect(lambda: self.set_tool(tool_enum))
            grp.addAction(action); tb.addAction(action); self.action_map[tool_enum] = action
            return action
        add_tool("画笔 (P)", ToolType.PEN, True).setShortcut("P")
        add_tool("橡皮 (E)", ToolType.ERASER).setShortcut("E")
        add_tool("选择 (S)", ToolType.SELECT).setShortcut("S")
        add_tool("顶点 (V)", ToolType.POINT).setShortcut("V")

    def set_tool(self, tool):
        self.canvas.current_tool = tool
        if tool in self.action_map: self.action_map[tool].setChecked(True)
        self.canvas.update()

    def create_menu(self):
        m = self.menuBar(); m.clear()
        fm = m.addMenu("文件")
        fm.addAction("导入图片...", self.import_img, "Ctrl+O")
        fm.addAction("导入 JSON...", self.import_json, "Ctrl+J") 
        fm.addSeparator()
        fm.addAction("导出画布...", self.export_img, "Ctrl+S")       
        fm.addAction("导出 JSON...", self.export_json, "Ctrl+Shift+S") 
        
        em = m.addMenu("编辑")
        em.addAction("撤销", self.do_undo, "Ctrl+Z") 
        em.addAction("重做", self.do_redo, "Ctrl+Y")
        em.addSeparator()
        em.addAction("复制", lambda: self.canvas.copy_action(), "Ctrl+C")
        em.addAction("剪切", lambda: self.canvas.cut_action(), "Ctrl+X")
        em.addAction("粘贴", lambda: self.canvas.paste_action(), "Ctrl+V")
        em.addSeparator()
        em.addAction("顺时针旋转 90°", lambda: self.canvas.rotate_action(True), "Ctrl+R")
        em.addAction("逆时针旋转 90°", lambda: self.canvas.rotate_action(False), "Ctrl+Shift+R")
        # --- 新增: 翻转快捷键 ---
        em.addAction("左右翻转", lambda: self.canvas.flip_action(True))
        em.addAction("上下翻转", lambda: self.canvas.flip_action(False))
        em.addSeparator()
        em.addAction("删除选区", self.canvas.delete_selection, "Delete")
        em.addAction("裁剪选区并另存...", self.crop_and_export, "Ctrl+Shift+C") 
        em.addAction("清空画布", self.do_clear, "Ctrl+Delete")
        em.addAction("选择颜色...", self.pick_color)

    def do_undo(self): self.canvas.model.undo(); self.canvas.update()
    def do_redo(self): self.canvas.model.redo(); self.canvas.update()
    def do_clear(self): self.canvas.model.clear_canvas(); self.refresh_region_list(); self.exit_edit_json_mode()

    def import_img(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open", "", "Images (*.png *.jpg *.bmp)")
        if path:
            img = QImage(path).convertToFormat(QImage.Format_ARGB32_Premultiplied)
            if not img.isNull():
                if self.canvas.model.is_canvas_empty():
                    self.canvas.model.load_image(img)
                else:
                    self.canvas.model.append_image_right(img)
                
                self.set_tool(ToolType.SELECT)
                self.refresh_region_list()
                self.exit_edit_json_mode()
                
                # --- 恢复自动选中和归中逻辑 ---
                if self.canvas.model.selection_rect:
                    self.canvas.fit_to_rect(self.canvas.model.selection_rect)
                self.update_selection_ui()

    def import_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入 JSON", "", "JSON Files (*.json)")
        if path:
            try:
                with open(path, 'r', encoding='utf-8') as f: data = json.load(f)
                self.canvas.model.load_json_regions(data); self.refresh_region_list()
            except Exception as e: QMessageBox.warning(self, "错误", str(e))

    def export_json(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出 JSON", "sprites.json", "JSON Files (*.json)")
        if path:
            ox, oy = self.canvas.model.layer_origin.x(), self.canvas.model.layer_origin.y()
            mh = self.canvas.model.main_layer.height(); export_data = {}
            for name, rect in self.canvas.model.json_regions.items():
                export_data[name] = {"x": rect.x()-ox, "y": oy+mh-rect.y()-rect.height(), "w": rect.width(), "h": rect.height()}
            with open(path, 'w', encoding='utf-8') as f: json.dump(export_data, f, indent=2, ensure_ascii=False)

    def on_region_selected(self, item):
        name = item.text()
        if name in self.canvas.model.json_regions:
            rect = self.canvas.model.json_regions[name]
            self.canvas.model.selection_rect = rect
            self.canvas.fit_to_rect(rect)
            self.update_selection_ui()

    def export_img(self):
        dlg = ExportDialog(self, self.canvas.model.selection_rect is not None)
        if dlg.exec_() == QDialog.Accepted:
            rect = self.canvas.model.selection_rect if dlg.should_export_selection() else self.canvas.get_content_rect()
            img = self.canvas.get_image(rect)
            if not img.isNull():
                path, _ = QFileDialog.getSaveFileName(self, "Save", "tex.png", "PNG (*.png)")
                if path: img.save(path)

    def crop_and_export(self):
        rect = self.canvas.model.selection_rect
        if not rect: return
        img = self.canvas.get_image(rect)
        if not img.isNull():
            path, _ = QFileDialog.getSaveFileName(self, "保存裁剪", "crop.png", "PNG (*.png)")
            if path: img.save(path)

    def pick_color(self):
        c = QColorDialog.getColor(self.canvas.current_color, self)
        if c.isValid(): self.canvas.current_color = c