# -*- coding: utf-8 -*-
import cv2
import time
from PySide6.QtCore import QThread, Signal
import insightface


class FaceMonitor(QThread):
    face_detected = Signal()
    face_lost     = Signal()
    alert         = Signal(str)

    ALERT_SEC = 60

    def __init__(self, camera_index=0, parent=None):
        super().__init__(parent)
        self._running        = False
        self._active         = False
        self._camera_index   = camera_index
        self._current_status = "REST"

    def set_driving_status(self, status: str):
        self._current_status = status

    def start_monitoring(self):
        self._active = True
        print("[FACE] เริ่ม monitor ใบหน้า")

    def stop_monitoring(self):
        self._active = False

    def stop(self):
        self._running = False
        self.wait()

    def run(self):
        self._running = True

        app = insightface.app.FaceAnalysis()
        app.prepare(ctx_id=0, det_size=(640, 640))

        cap = cv2.VideoCapture(self._camera_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            print("[FACE ERROR] เปิดกล้องไม่ได้")
            return

        last_seen   = time.time()
        alerted     = False
        prev_status = None

        while self._running:
            ret, frame = cap.read()
            if not ret or not self._active:
                time.sleep(0.1)
                continue

            # ── ตอนพัก reset เวลา ไม่แจ้งเตือน ──────────────────────
            if self._current_status in ["REST", "WAIT_NEW_DAY"]:
                last_seen = time.time()
                alerted   = False
                # ถ้าก่อนหน้านี้แสดง lost อยู่ → เปลี่ยนเป็น found ตอนพัก
                if prev_status != "found":
                    prev_status = "found"
                    self.face_detected.emit()
                time.sleep(0.1)
                continue

            # ── ตอนขับ → ตรวจจับใบหน้า ───────────────────────────────
            faces = app.get(frame)

            if faces:
                last_seen = time.time()
                alerted   = False
                if prev_status != "found":
                    prev_status = "found"
                    self.face_detected.emit()
            else:
                lost_sec = time.time() - last_seen
                if prev_status != "lost":
                    prev_status = "lost"
                    self.face_lost.emit()

                if lost_sec >= self.ALERT_SEC and not alerted:
                    msg = f"ไม่พบใบหน้าผู้ขับขี่ขณะขับรถนาน {lost_sec:.0f} วินาที!"
                    print(f"[ALERT] {msg}")
                    self.alert.emit(msg)
                    alerted = True

            time.sleep(0.03)

        cap.release()