from PyQt5.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QPixmap

from utils import blend_color_image

class ExportDialog(QDialog):
    def __init__(self, parent=None, has_selection=False):
        super().__init__(parent)
        self.setWindowTitle("导出选项")
        self.resize(300, 150)
        layout = QVBoxLayout(self)
        
        self.radio_all = QRadioButton("导出全部内容 (自动裁剪)")
        self.radio_sel = QRadioButton("仅导出选中区域")
        
        self.radio_all.setChecked(True)
        if not has_selection:
            self.radio_sel.setEnabled(False)
            self.radio_sel.setText("仅导出选中区域 (无选区)")
            
        layout.addWidget(self.radio_all)
        layout.addWidget(self.radio_sel)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
    def should_export_selection(self):
        return self.radio_sel.isChecked()


class ScaleSelectionDialog(QDialog):
    def __init__(self, selection_width, selection_height, parent=None):
        super().__init__(parent)
        self.selection_width = selection_width
        self.selection_height = selection_height
        self._syncing_values = False

        self.setWindowTitle("缩放选区")
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.sampling_combo = QComboBox()
        self.sampling_combo.addItem("双线性插值采样", "bilinear")
        self.sampling_combo.addItem("临近点采样", "nearest")
        form.addRow("采样方式：", self.sampling_combo)

        self.center_combo = QComboBox()
        self.center_combo.addItem("左下角", "bottom_left")
        self.center_combo.addItem("左上角", "top_left")
        self.center_combo.addItem("中心", "center")
        self.center_combo.addItem("右上角", "top_right")
        self.center_combo.addItem("右下角", "bottom_right")
        form.addRow("缩放中心：", self.center_combo)

        self.scale_x_spin = self._make_scale_spinbox()
        self.scale_y_spin = self._make_scale_spinbox()
        form.addRow("水平倍率：", self.scale_x_spin)
        form.addRow("垂直倍率：", self.scale_y_spin)

        self.target_width_spin = self._make_size_spinbox(selection_width)
        self.target_height_spin = self._make_size_spinbox(selection_height)
        form.addRow("目标宽度：", self.target_width_spin)
        form.addRow("目标高度：", self.target_height_spin)

        self.keep_aspect_checkbox = QCheckBox("锁定宽高比例")
        self.keep_aspect_checkbox.setChecked(True)
        form.addRow("", self.keep_aspect_checkbox)
        layout.addLayout(form)

        self.output_size_label = QLabel()
        layout.addWidget(self.output_size_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.scale_x_spin.valueChanged.connect(self._scale_x_changed)
        self.scale_y_spin.valueChanged.connect(self._scale_y_changed)
        self.target_width_spin.valueChanged.connect(self._target_width_changed)
        self.target_height_spin.valueChanged.connect(self._target_height_changed)
        self.keep_aspect_checkbox.toggled.connect(self._aspect_toggled)
        self._update_output_size()

    @staticmethod
    def _make_scale_spinbox():
        spin = QDoubleSpinBox()
        spin.setRange(0.00000001, 100000.00000000)
        spin.setDecimals(8)
        spin.setSingleStep(0.0001)
        spin.setValue(1.00000000)
        spin.setSuffix(" ×")
        return spin

    @staticmethod
    def _make_size_spinbox(value):
        spin = QSpinBox()
        spin.setRange(1, 100000)
        spin.setValue(max(1, int(value)))
        spin.setSuffix(" px")
        return spin

    def _scale_x_changed(self, value):
        if self._syncing_values:
            return
        self._syncing_values = True
        self.target_width_spin.setValue(
            max(1, round(self.selection_width * value))
        )
        if self.keep_aspect_checkbox.isChecked():
            self.scale_y_spin.setValue(value)
            self.target_height_spin.setValue(
                max(1, round(self.selection_height * value))
            )
        self._syncing_values = False
        self._update_output_size()

    def _scale_y_changed(self, value):
        if self._syncing_values:
            return
        self._syncing_values = True
        self.target_height_spin.setValue(
            max(1, round(self.selection_height * value))
        )
        if self.keep_aspect_checkbox.isChecked():
            self.scale_x_spin.setValue(value)
            self.target_width_spin.setValue(
                max(1, round(self.selection_width * value))
            )
        self._syncing_values = False
        self._update_output_size()

    def _target_width_changed(self, value):
        if self._syncing_values:
            return
        factor = value / self.selection_width
        self._syncing_values = True
        self.scale_x_spin.setValue(factor)
        if self.keep_aspect_checkbox.isChecked():
            self.scale_y_spin.setValue(factor)
            self.target_height_spin.setValue(
                max(1, round(self.selection_height * factor))
            )
        self._syncing_values = False
        self._update_output_size()

    def _target_height_changed(self, value):
        if self._syncing_values:
            return
        factor = value / self.selection_height
        self._syncing_values = True
        self.scale_y_spin.setValue(factor)
        if self.keep_aspect_checkbox.isChecked():
            self.scale_x_spin.setValue(factor)
            self.target_width_spin.setValue(
                max(1, round(self.selection_width * factor))
            )
        self._syncing_values = False
        self._update_output_size()

    def _aspect_toggled(self, checked):
        if checked:
            factor = self.scale_x_spin.value()
            self._syncing_values = True
            self.scale_y_spin.setValue(factor)
            self.target_width_spin.setValue(
                max(1, round(self.selection_width * factor))
            )
            self.target_height_spin.setValue(
                max(1, round(self.selection_height * factor))
            )
            self._syncing_values = False
        self._update_output_size()

    def _update_output_size(self):
        self.output_size_label.setText(
            f"最终尺寸：{self.target_width_spin.value()} × "
            f"{self.target_height_spin.value()} px"
        )

    def sampling_mode(self):
        return self.sampling_combo.currentData()

    def scale_center(self):
        return self.center_combo.currentData()

    def scale_factors(self):
        return self.scale_x_spin.value(), self.scale_y_spin.value()

    def target_size(self):
        return self.target_width_spin.value(), self.target_height_spin.value()


class ColorOverlayDialog(QDialog):
    PREVIEW_WIDTH = 360
    PREVIEW_HEIGHT = 220

    def __init__(self, source_image, initial_color=None, parent=None):
        super().__init__(parent)
        self.source_image = source_image.copy()
        self._color = QColor(initial_color or QColor(255, 255, 255, 255))

        self.setWindowTitle("叠加颜色")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)

        self.preview_label = QLabel()
        self.preview_label.setFixedSize(
            self.PREVIEW_WIDTH, self.PREVIEW_HEIGHT
        )
        self.preview_label.setFrameShape(QFrame.StyledPanel)
        self.preview_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.preview_label, alignment=Qt.AlignHCenter)

        form = QFormLayout()
        color_row = QHBoxLayout()
        self.color_button = QPushButton()
        self.color_button.setMinimumHeight(34)
        self.color_button.clicked.connect(self._choose_color)
        color_row.addWidget(self.color_button)
        form.addRow("叠加颜色：", color_row)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("正常", "normal")
        self.mode_combo.addItem("覆盖", "replace")
        self.mode_combo.addItem("正片叠底", "multiply")
        self.mode_combo.addItem("滤色", "screen")
        self.mode_combo.addItem("叠加", "overlay")
        self.mode_combo.addItem("柔光", "soft_light")
        self.mode_combo.addItem("强光", "hard_light")
        self.mode_combo.addItem("变暗", "darken")
        self.mode_combo.addItem("变亮", "lighten")
        self.mode_combo.addItem("颜色减淡", "color_dodge")
        self.mode_combo.addItem("颜色加深", "color_burn")
        self.mode_combo.addItem("差值", "difference")
        self.mode_combo.addItem("相加", "plus")
        self.mode_combo.currentIndexChanged.connect(self._update_preview)
        form.addRow("混合模式：", self.mode_combo)
        layout.addLayout(form)

        hint = QLabel(
            "“覆盖”直接写入目标 RGBA；其他模式将颜色 Alpha 作为"
            "叠加强度，并保持选区原透明度。"
        )
        hint.setStyleSheet("color: #888;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_color_button()
        self._update_preview()

    def _choose_color(self):
        color = QColorDialog.getColor(
            self._color,
            self,
            "选择叠加颜色",
            QColorDialog.ShowAlphaChannel,
        )
        if color.isValid():
            self._color = QColor(color)
            self._refresh_color_button()
            self._update_preview()

    def _refresh_color_button(self):
        color = self._color
        luminance = color.red() * 299 + color.green() * 587 + color.blue() * 114
        text_color = "#111" if luminance >= 150000 and color.alpha() >= 128 else "#fff"
        self.color_button.setText(
            f"ARGB: ({color.alpha()},{color.red()},"
            f"{color.green()},{color.blue()}) · 点击选择"
        )
        self.color_button.setStyleSheet(
            f"background-color: rgba({color.red()}, {color.green()}, "
            f"{color.blue()}, {color.alpha()}); color: {text_color}; "
            "border: 1px solid #666; padding: 5px;"
        )

    def _update_preview(self):
        preview = blend_color_image(
            self.source_image, self._color, self.blend_mode()
        )
        available_width = self.PREVIEW_WIDTH - 20
        available_height = self.PREVIEW_HEIGHT - 20
        if not preview.isNull():
            preview = preview.scaled(
                available_width,
                available_height,
                Qt.KeepAspectRatio,
                Qt.FastTransformation,
            )

        background = QImage(
            self.PREVIEW_WIDTH,
            self.PREVIEW_HEIGHT,
            QImage.Format_RGB32,
        )
        painter = QPainter(background)
        tile_size = 12
        colors = (QColor("#5c5c5c"), QColor("#747474"))
        for y in range(0, self.PREVIEW_HEIGHT, tile_size):
            for x in range(0, self.PREVIEW_WIDTH, tile_size):
                painter.fillRect(
                    x,
                    y,
                    tile_size,
                    tile_size,
                    colors[(x // tile_size + y // tile_size) % 2],
                )
        if not preview.isNull():
            x = (self.PREVIEW_WIDTH - preview.width()) // 2
            y = (self.PREVIEW_HEIGHT - preview.height()) // 2
            painter.drawImage(x, y, preview)
        painter.end()
        self.preview_label.setPixmap(QPixmap.fromImage(background))

    def selected_color(self):
        return QColor(self._color)

    def blend_mode(self):
        return self.mode_combo.currentData() or "normal"
