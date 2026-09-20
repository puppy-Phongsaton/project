import cv2
import time
from PySide6.QtCore import QThread, Signal
import insightface


class FaceMonitor(QThread):

    face_detected = Signal()
    face_lost = Signal()
    alert = Signal(str)

    ALERT_SEC = 60

    def __init__(self, camera_index=0, parent=None):
        super().__init__(parent)

        self._running = False
        self._active = False
        self._camera_index = camera_index
        self._current_status = "REST"

    # ─────────────────────────────────────────────
    # รับสถานะจาก DriverApp
    # ─────────────────────────────────────────────
    def set_driving_status(self, status: str):
        self._current_status = status
        print(f"[FACE] Driver status = {status}")

    # ─────────────────────────────────────────────
    # เริ่มตรวจ
    # ─────────────────────────────────────────────
    def start_monitoring(self):
        self._active = True
        print("[FACE] เริ่ม monitor ใบหน้า")

    # ─────────────────────────────────────────────
    # หยุดตรวจ
    # ─────────────────────────────────────────────
    def stop_monitoring(self):
        self._active = False
        print("[FACE] หยุด monitor ใบหน้า")

    # ─────────────────────────────────────────────
    # Stop thread
    # ─────────────────────────────────────────────
    def stop(self):
        self._running = False
        self.wait()

    # ─────────────────────────────────────────────
    # Thread
    # ─────────────────────────────────────────────
    def run(self):

        self._running = True

        try:

            # =================================================
            # LOAD INSIGHTFACE
            # =================================================

            print("[FACE] กำลังโหลด InsightFace...")

            app = insightface.app.FaceAnalysis()

            # Raspberry Pi ใช้ CPU
            app.prepare(
                ctx_id=-1,
                det_size=(320, 320)
            )

            print("[FACE] InsightFace พร้อมทำงาน")

            # =================================================
            # OPEN CAMERA
            # =================================================

            print("[FACE] กำลังเปิดกล้อง...")

            # Raspberry Pi ใช้ V4L2
            cap = cv2.VideoCapture(
                self._camera_index,
                cv2.CAP_V4L2
            )

            cap.set(
                cv2.CAP_PROP_FRAME_WIDTH,
                640
            )

            cap.set(
                cv2.CAP_PROP_FRAME_HEIGHT,
                480
            )

            cap.set(
                cv2.CAP_PROP_FPS,
                15
            )

            if not cap.isOpened():

                print(
                    "[FACE ERROR] เปิดกล้องไม่ได้"
                )

                return

            print("[FACE] เปิดกล้องสำเร็จ")

            # =================================================
            # FACE STATE
            # =================================================

            last_seen = time.time()

            alerted = False

            # None / found / lost
            prev_status = None

            # =================================================
            # MAIN LOOP
            # =================================================

            while self._running:

                ret, frame = cap.read()

                # -----------------------------
                # อ่านกล้องไม่ได้
                # -----------------------------

                if not ret:

                    print(
                        "[FACE ERROR] อ่านภาพจากกล้องไม่ได้"
                    )

                    time.sleep(0.2)

                    continue

                # -----------------------------
                # Monitor ยังไม่ active
                # -----------------------------

                if not self._active:

                    time.sleep(0.1)

                    continue

                # =================================================
                # REST / WAIT NEW DAY
                # ไม่ต้องตรวจหน้า
                # =================================================

                if self._current_status in [
                    "REST",
                    "WAIT_NEW_DAY"
                ]:

                    last_seen = time.time()

                    alerted = False

                    # ตอนพักถือว่า Camera True
                    if prev_status != "found":

                        prev_status = "found"

                        print(
                            "[FACE] REST → Camera True"
                        )

                        self.face_detected.emit()

                    time.sleep(0.1)

                    continue

                # =================================================
                # DRIVING / WARN / OVER
                # ตรวจใบหน้า
                # =================================================

                faces = app.get(frame)

                # =================================================
                # FOUND
                # =================================================

                if len(faces) > 0:

                    last_seen = time.time()

                    alerted = False

                    if prev_status != "found":

                        prev_status = "found"

                        print(
                            "[FACE] พบใบหน้า"
                        )

                        self.face_detected.emit()

                # =================================================
                # LOST
                # =================================================

                else:

                    lost_sec = (
                        time.time() - last_seen
                    )

                    if prev_status != "lost":

                        prev_status = "lost"

                        print(
                            "[FACE] ไม่พบใบหน้า"
                        )

                        self.face_lost.emit()

                    # =================================================
                    # ALERT 60 SEC
                    # =================================================

                    if (
                        lost_sec >= self.ALERT_SEC
                        and not alerted
                    ):

                        msg = (
                            "ไม่พบใบหน้าผู้ขับขี่ "
                            f"ขณะขับรถนาน "
                            f"{lost_sec:.0f} วินาที!"
                        )

                        print(
                            f"[ALERT] {msg}"
                        )

                        self.alert.emit(msg)

                        alerted = True

                # =================================================
                # ไม่แสดงภาพ
                # =================================================

                time.sleep(0.03)

            # =================================================
            # RELEASE CAMERA
            # =================================================

            cap.release()

            print(
                "[FACE] ปิดกล้องแล้ว"
            )

        # =====================================================
        # ERROR
        # =====================================================

        except Exception as e:

            print(
                "[FACE ERROR]",
                type(e).__name__,
                str(e)
            )

        finally:

            print(
                "[FACE] thread stopped"
            )