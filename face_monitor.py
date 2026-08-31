# -*- coding: utf-8 -*-
import cv2
import time
from PySide6.QtCore import QThread, Signal
import insightface


class FaceMonitor(QThread):
    face_detected = Signal()   # emit เมื่อสถานะเปลี่ยนจาก lost → detected
    face_lost     = Signal()   # emit เมื่อสถานะเปลี่ยนจาก detected → lost
    alert         = Signal(str)

    ALERT_SEC = 60

    def __init__(self, camera_index=0, parent=None):
        super().__init__(parent)
        self._running      = False
        self._active       = False
        self._camera_index = camera_index

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

        cap = cv2.VideoCapture(self._camera_index)
        if not cap.isOpened():
            print("[FACE ERROR] เปิดกล้องไม่ได้")
            return

        last_seen    = time.time()
        alerted      = False
        prev_status  = None   # "found" | "lost" — ส่ง signal เฉพาะตอนเปลี่ยนสถานะ

        while self._running:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.1)
                continue

            if not self._active:
                time.sleep(0.1)
                continue

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
                    msg = f"ไม่เห็นใบหน้าคนขับ {lost_sec:.1f} วิ"
                    print(f"[ALERT] {msg}")
                    self.alert.emit(msg)
                    alerted = True

        cap.release()