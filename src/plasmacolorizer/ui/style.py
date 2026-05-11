"""Quiet dark UI skin; works alongside Plasma themes."""

APP_STYLESHEET = """
QWidget {
  font-size: 13px;
  color: #e8e8ef;
}
QMainWindow {
  background: #0f0f14;
}
QLabel {
  color: #e8e8ef;
}
QGroupBox {
  color: #ececf3;
  border: 1px solid #2c2c38;
  border-radius: 10px;
  margin-top: 12px;
  padding: 14px 12px 12px 12px;
  font-weight: 600;
  background: #16161e;
}
QGroupBox::title {
  subcontrol-origin: margin;
  left: 16px;
  padding: 0 6px;
}
QTabWidget::pane {
  border: 1px solid #2a2a34;
  border-radius: 10px;
  top: -1px;
  background: #12121a;
}
QTabBar::tab {
  background: #1a1a24;
  color: #b8b8c8;
  border: 1px solid #2a2a34;
  border-bottom: none;
  border-top-left-radius: 8px;
  border-top-right-radius: 8px;
  padding: 10px 18px;
  margin-right: 4px;
}
QTabBar::tab:selected {
  background: #12121a;
  color: #f2f2f8;
  font-weight: 600;
}
QTabBar::tab:hover:!selected {
  background: #22222c;
  color: #e4e4ec;
}
QScrollArea {
  border: none;
  background: transparent;
}
QLineEdit, QSpinBox, QComboBox {
  background: #1c1c26;
  border: 1px solid #343442;
  border-radius: 8px;
  padding: 8px 10px;
  color: #f6f6fb;
  selection-background-color: #3d7ec4;
  selection-color: #ffffff;
}
QComboBox QAbstractItemView {
  background: #1c1c26;
  color: #f2f2f8;
  selection-background-color: #3d7ec4;
  selection-color: #ffffff;
  border: 1px solid #343442;
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
  background: #2a2a36;
  color: #f0f0f6;
}
QPushButton#secondary:hover {
  background: #34344a;
}
QSlider::groove:horizontal {
  height: 8px;
  background: #1c1c26;
  border-radius: 4px;
}
QSlider::handle:horizontal {
  width: 18px;
  background: #5bc986;
  margin: -6px 0;
  border-radius: 9px;
}
QTextEdit {
  background: #0c0c12;
  color: #e2e2ea;
  border: 1px solid #2a2a34;
  border-radius: 10px;
  padding: 8px;
  selection-background-color: #3d7ec4;
  selection-color: #ffffff;
}

/* Alerts / progress: Fusion + app QSS often leaves dialogs light while text stays
   tuned for the main window — force dark chrome + light body copy. */
QMessageBox {
  background-color: #24242e;
}
QMessageBox QLabel {
  color: #f6f6fc;
  background-color: transparent;
}
QMessageBox QPushButton {
  background-color: #3a8eef;
  color: #0d1117;
  min-width: 88px;
  padding: 8px 14px;
}
QMessageBox QPushButton:hover {
  background-color: #5aa0f5;
}
QDialog {
  background-color: #1a1a22;
}
QDialog QLabel {
  color: #f2f2f8;
}
QProgressDialog {
  background-color: #1a1a22;
}
QProgressDialog QLabel {
  color: #f4f4fa;
}
QProgressBar {
  background-color: #1c1c26;
  border: 1px solid #343442;
  border-radius: 6px;
  text-align: center;
  color: #f0f0f6;
  min-height: 22px;
}
QProgressBar::chunk {
  background-color: #3a8eef;
  border-radius: 5px;
}

QToolTip {
  background-color: #2a2a34;
  color: #fafaff;
  border: 1px solid #45455a;
  padding: 6px 8px;
}
"""
