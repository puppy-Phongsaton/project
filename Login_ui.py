# -*- coding: utf-8 -*-
"""
login_window.py
หน้า login รูดบัตรใบขับขี่ด้วย MSR90 magnetic card reader
"""

import re
import ctypes
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QLineEdit
from PySide6.QtCore    import Qt, Signal
from PySide6.QtGui     import QFont

# เปลี่ยน Keyboard Layout เป็น English (US) เพื่อให้อ่านบัตรได้ถูกต้อง
try:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.LoadKeyboardLayoutW("00000409", 1)
except Exception:
    pass  # ไม่ใช่ Windows (RPi) ข้ามไป

# regex เดียวกับ CardReader.py เดิม
_CARD_PATTERN = re.compile(r"\^([^$]+)\$([^$]+)\$[^^]*\^\^(\d+)=")


class LoginWindow(QWidget):
    login_success = Signal(str, str, str)  # driver_id, firstname, lastname

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Driver Login")
        self.setFixedSize(450, 280)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(16)
        layout.setContentsMargins(40, 40, 40, 40)

        title = QLabel("กรุณารูดบัตรใบขับขี่")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Tahoma", 18))
        layout.addWidget(title)

        hint = QLabel("🪪  Swipe your license card")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setFont(QFont("Tahoma", 11))
        hint.setStyleSheet("color: gray;")
        layout.addWidget(hint)

        self.lbl_name = QLabel("-")
        self.lbl_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_name.setFont(QFont("Tahoma", 16))
        layout.addWidget(self.lbl_name)

        self.lbl_id = QLabel("-")
        self.lbl_id.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_id.setFont(QFont("Tahoma", 14))
        self.lbl_id.setStyleSheet("color: gray;")
        layout.addWidget(self.lbl_id)

        self.status = QLabel("")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setFont(QFont("Tahoma", 10))
        layout.addWidget(self.status)

        # input ซ่อนไว้รับ card data
        self.card_input = QLineEdit()
        self.card_input.setMaximumHeight(1)
        self.card_input.setStyleSheet("border: none; background: transparent;")
        self.card_input.returnPressed.connect(self._on_card_input)
        layout.addWidget(self.card_input)

        self.setLayout(layout)

    def showEvent(self, event):
        super().showEvent(event)
        self.card_input.setFocus()

    def mousePressEvent(self, event):
        self.card_input.setFocus()

    def _on_card_input(self):
        raw = self.card_input.text().strip()
        self.card_input.clear()
        self.card_input.setFocus()

        if not raw:
            return

        m = _CARD_PATTERN.search(raw)
        if m:
            lastname  = m.group(1)
            firstname = m.group(2)
            driver_id = m.group(3)[-13:]   # 13 หลักสุดท้าย

            self.lbl_name.setText(f"{firstname} {lastname}")
            self.lbl_name.setStyleSheet("color: green;")
            self.lbl_id.setText(driver_id)
            self.status.setText("✅ กำลังเข้าสู่ระบบ...")
            self.status.setStyleSheet("color: green;")

            print(f"[LOGIN] id={driver_id} name={firstname} {lastname}")
            self.login_success.emit(driver_id, firstname, lastname)
            self.close()
        else:
            self.lbl_name.setText("ไม่พบข้อมูล")
            self.lbl_name.setStyleSheet("color: red;")
            self.lbl_id.setText("-")
            self.status.setText("❌ บัตรไม่ถูกต้อง กรุณารูดใหม่")
            self.status.setStyleSheet("color: red;")