"""Quiet dark UI skin; works alongside Plasma themes."""

APP_STYLESHEET = """
QWidget {
  font-size: 13px;
}
QMainWindow {
  background: #1e1e24;
}
QLabel {
  color: #e6e6ea;
}
QGroupBox {
  color: #e6e6ea;
  border: 1px solid #3a3a44;
  border-radius: 10px;
  margin-top: 12px;
  padding: 14px 12px 12px 12px;
  font-weight: 600;
  background: #25252d;
}
QGroupBox::title {
  subcontrol-origin: margin;
  left: 16px;
  padding: 0 6px;
}
QLineEdit, QSpinBox, QComboBox {
  background: #2e2e38;
  border: 1px solid #444;
  border-radius: 8px;
  padding: 8px 10px;
  color: #f4f4f8;
  selection-background-color: #4a8fd8;
}
QPushButton {
  background: #3a8eef;
  color: #0d1117;
  border: none;
  border-radius: 10px;
  padding: 10px 16px;
  font-weight: 600;
}
QPushButton:hover {
  background: #5aa0f5;
}
QPushButton:pressed {
  background: #2f78d6;
}
QPushButton#secondary {
  background: #353545;
  color: #ececf0;
}
QPushButton#secondary:hover {
  background: #3d3d50;
}
QSlider::groove:horizontal {
  height: 8px;
  background: #2e2e38;
  border-radius: 4px;
}
QSlider::handle:horizontal {
  width: 18px;
  background: #6bd491;
  margin: -6px 0;
  border-radius: 9px;
}
QTextEdit {
  background: #1a1a20;
  color: #dcdce4;
  border: 1px solid #3a3a44;
  border-radius: 10px;
  padding: 8px;
}
"""
