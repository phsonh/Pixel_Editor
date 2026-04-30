from enum import Enum
from PyQt5.QtGui import QColor

# 工具类型枚举
class ToolType(Enum):
    PEN = 1     # 画笔
    ERASER = 2  # 橡皮
    SELECT = 3  # 选择/移动
    POINT = 4   # 顶点模式

# 默认配置
DEFAULT_WIDTH = 128
DEFAULT_HEIGHT = 128
DEFAULT_COLOR = QColor(255, 0, 0, 255)
BACKGROUND_COLOR = QColor(30, 30, 30)