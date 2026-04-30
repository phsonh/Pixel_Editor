@echo off
echo 正在使用Nuitka编译
python -m venv venv_build && call .\venv_build\Scripts\activate && python -m pip install --upgrade pip && pip install PyQt5 nuitka zstandard && python -m nuitka --standalone --onefile --windows-console-mode=disable --enable-plugin=pyqt5 --remove-output --output-dir=dist main.py && echo 编译完成 && pause