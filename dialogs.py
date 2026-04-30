from PyQt5.QtWidgets import QDialog, QVBoxLayout, QRadioButton, QDialogButtonBox

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