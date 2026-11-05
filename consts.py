from enum import Enum
from PyQt5.QtGui import QColor


class ToolType(Enum):
    PEN = 1
    ERASER = 2
    SELECT = 3
    POINT = 4


class CoordinateMode(Enum):
    """Canvas display and JSON coordinate convention."""

    TOP_LEFT_Y_DOWN = "top_left_y_down"
    BOTTOM_LEFT_Y_UP = "bottom_left_y_up"

    @property
    def y_down(self):
        return self is CoordinateMode.TOP_LEFT_Y_DOWN

    @property
    def display_name(self):
        if self.y_down:
            return "左上角原点，Y 向下"
        return "左下角原点，Y 向上"


DEFAULT_WIDTH = 128
DEFAULT_HEIGHT = 128
DEFAULT_COLOR = QColor(255, 0, 0, 255)
BACKGROUND_COLOR = QColor(30, 30, 30)
