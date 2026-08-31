# -*- coding: utf-8 -*-
import sys
import time
import uuid
from datetime import datetime

from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtCore    import QTimer, Qt

from new_ui import Ui_MainWindow
from driver_logic   import DriverLogic, MIN_SPEED, REST_TIME, save_state, load_state, STATE_FILE
from datapost       import post_realtime, post_trigger, close as db_close
from Login_ui       import LoginWindow
from face_monitor   import FaceMonitor
from gps_worker     import GpsWorker

GPS_PORT = "/dev/ttyAMA0"
GPS_BAUD = 9600

_C = {
    "DRIVING":      ("#00FF7F", "rgba(0,255,127,20)"),
    "WARN":         ("#FFD700", "rgba(255,215,0,20)"),
    "OVER":         ("#FF3333", "rgba(255,51,51,20)"),
    "REST":         ("#00BFFF", "rgba(0,191,255,20)"),
    "WAIT_NEW_DAY": ("#FF8C00", "rgba(255,140,0,20)"),
}
_STATUS_TEXT = {
    "DRIVING":      "DRIVING",
    "WARN":         "Warning",
    "OVER":         "OVER TIME",
    "REST":         "REST",
    "WAIT_NEW_DAY": "WAIT NEW DAY",
}

GPS_CHECK_INTERVAL  = 5

# status code สำหรับส่ง DB
_STATUS_CODE = {
    "REST":         0,
    "DRIVING":      1,
    "WARN":         2,
    "OVER":         3,
    "WAIT_NEW_DAY": 4,
}
DB_SEND_INTERVAL    = 5
DRIVER_ID           = "123456789"
TRUCK_ID            = ':'.join(f'{(uuid.getnode() >> i) & 0xff:02x}' for i in range(40, -1, -8))


def _fmt(seconds: float) -> str:
    s = max(0, int(seconds))
    h, r = divmod(s, 3600)
    m, sc = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{sc:02d}"


class DriverApp(QMainWindow):
    def __init__(self, driver_id: str = "123456789", firstname: str = "", lastname: str = ""):
        super().__init__()
        self.ui    = Ui_MainWindow()
        self.ui.setupUi(self)
        self.logic      = DriverLogic()
        self.driver_id = driver_id
        load_state(self.logic)
        self.ui.Driver_Name.setText(f"{firstname} {lastname}")
        self.ui.Driver_ID.setText(driver_id)

        # ── Face Monitor ── สร้างก่อน start_monitoring
        self.face_monitor = FaceMonitor(camera_index=0)
        self.face_monitor.alert.connect(self._on_face_alert)
        self.face_monitor.face_detected.connect(self._on_face_detected)
        self.face_monitor.face_lost.connect(self._on_face_lost)
        self.face_monitor.start()
        self.face_monitor.start_monitoring()

        self._gps_fixed   = False
        self._last_gps_t  = time.time()
        self._last_tick_t = time.time()
        self._last_pos    = (0.0, 0.0, 0.0, 'DRIVING')  # lat, lon, speed, status

        self.worker = GpsWorker(port=GPS_PORT, baud=GPS_BAUD)
        self.worker.data_ready.connect(self._on_gps_data)
        self.worker.no_fix.connect(self._on_no_fix)
        self.worker.no_gps.connect(self._on_no_gps)
        self.worker.start()

        self._fix_timer = QTimer()
        self._fix_timer.setInterval(GPS_CHECK_INTERVAL * 1000)
        self._fix_timer.timeout.connect(self._check_fix_timeout)
        self._fix_timer.start()

        self._db_timer = QTimer()
        self._db_timer.setInterval(DB_SEND_INTERVAL * 1000)
        self._db_timer.timeout.connect(self._send_realtime)
        self._db_timer.start()

        self._clock = QTimer()
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._update_clock)
        self._clock.start()

        self._set_no_gps()
        self._update_clock()
        self.ui.label_23.setText("Camera :")
        self.ui.Rest_Next.setText("--")
        self.ui.Rest_Next.setStyleSheet("color: gray; font: 16pt 'Segoe UI';")



    # ─── center widgets after render ─────────────────────────
    def _center_widgets(self):
        for widget, frame in [
            (self.ui.Val_1,          self.ui.frame_2),
            (self.ui.Speed,          self.ui.frame_3),
            (self.ui.Driving_Status, self.ui.Status_frame),
        ]:
            widget.adjustSize()
            new_x = (frame.width() - widget.width()) // 2
            widget.move(new_x, widget.y())

    def _center_status(self):
        """เรียกหลัง setText เพื่อ center Driving_Status ใหม่"""
        w = self.ui.Driving_Status
        w.adjustSize()
        new_x = (self.ui.Status_frame.width() - w.width()) // 2
        w.move(new_x, w.y())

    # ─── keyboard (sim only) ─────────────────────────────────
    def keyPressEvent(self, event):
        from GPS_Module import IS_RPI
        if not IS_RPI and event.key() == Qt.Key.Key_S:
            self.worker.force_stop = not self.worker.force_stop
            state = "STOP" if self.worker.force_stop else "DRIVE"
            print(f"[SIM] S → {state}")
        if not IS_RPI and event.key() == Qt.Key.Key_R:
            import os
            if os.path.exists(STATE_FILE):
                os.remove(STATE_FILE)
            self.logic.__init__()
            print("[SIM] R → RESET")
        super().keyPressEvent(event)

    # ─── GPS callbacks ───────────────────────────────────────
    def _on_gps_data(self, lat, lon, raw_speed, t_str, d_str):
        now   = time.time()
        delta = now - self._last_tick_t
        self._last_tick_t = now
        self._last_gps_t  = now

        speed = self.logic.smooth_speed(raw_speed)
        self.logic.tick(delta, speed)
        save_state(self.logic)
        self._last_pos = (lat, lon, speed, _STATUS_CODE.get(self.logic.status, 0))

        if self.logic.pending_rest_payload:
            p = self.logic.pending_rest_payload
            post_trigger(self.driver_id, TRUCK_ID,
                         p["drive_duration"], p["rest_duration"],
                         p["rest_start"], p["rest_end"])
            self.logic.pending_rest_payload = None

        if not self._gps_fixed:
            self._gps_fixed = True
            self._set_fixed()

        self._refresh_ui(lat, lon, speed)

    def _on_no_fix(self):
        """เจอ GPS แต่ยังหาตำแหน่งไม่ได้"""
        self.logic.smooth_speed(0)
        self._last_gps_t  = time.time()
        self._gps_fixed   = False
        self.ui.GPS_Status.setText("NO FIX")
        self.ui.GPS_Status.setStyleSheet("color: #FFD700; font: 12pt 'Segoe UI';")
        self.ui.Latitude.setText("None")
        self.ui.Longtitude.setText("None")

    def _on_no_gps(self):
        """ไม่ได้รับข้อมูลจาก GPS เลย"""
        # ไม่ reset _last_gps_t เพราะยังไม่เจออุปกรณ์
        pass   # ให้ _check_fix_timeout จัดการแทน

    # ─── GPS status display ──────────────────────────────────
    def _set_no_gps(self):
        """ไม่พบ GPS"""
        self._gps_fixed = False
        self.ui.GPS_Status.setText("NO GPS")
        self.ui.GPS_Status.setStyleSheet("color: #FF3333; font: 12pt 'Segoe UI';")
        self.ui.Latitude.setText("None")
        self.ui.Longtitude.setText("None")

    def _set_fixed(self):
        """GPS fix สมบูรณ์"""
        self.ui.GPS_Status.setText("GPS FIXED")
        self.ui.GPS_Status.setStyleSheet("color: #00FF7F; font: 12pt 'Segoe UI';")

    def _check_fix_timeout(self):
        """ถ้าไม่ได้รับข้อมูลนานเกิน GPS_CHECK_INTERVAL → NO GPS"""
        if time.time() - self._last_gps_t > GPS_CHECK_INTERVAL:
            self._set_no_gps()

    # ─── Clock ───────────────────────────────────────────────
    def _update_clock(self):
        now = datetime.now()
        self.ui.Time.setText(now.strftime("%H:%M:%S"))
        self.ui.Date.setText(now.strftime("%d/%m/%Y"))

    # ─── UI refresh ──────────────────────────────────────────
    def _refresh_ui(self, lat, lon, speed):
        ui = self.ui
        lg = self.logic

        ui.Speed.setText(f"{speed:.1f}")
        ui.Latitude.setText(f"{lat:.5f}")
        ui.Longtitude.setText(f"{lon:.5f}")

        # ── Main_status / Main_Val (Val_1) เปลี่ยนตาม speed ──
        if lg.end_of_day:
            ui.Main_status.setText("Wait New Day")
            ui.Val_1.setText(_fmt(lg.rest_remaining))
            ui.Sub_status.setText("Rested")
            ui.Val_2.setText(_fmt(lg.new_day_waited))
        elif lg.speed < MIN_SPEED:
            ui.Main_status.setText("Rest Time")
            ui.Val_1.setText(_fmt(lg.stop_duration))
            ui.Sub_status.setText("Driving")
            ui.Val_2.setText(_fmt(lg.elapsed_time))
        else:
            ui.Main_status.setText("Driving Time")
            ui.Val_1.setText(_fmt(lg.elapsed_time))
            ui.Sub_status.setText("Rest")
            ui.Val_2.setText(_fmt(lg.stop_duration))

        ui.Drive_R1_Val.setText(_fmt(lg.round_times[0]))
        ui.Drive_R2_val.setText(_fmt(lg.round_times[1]))
        ui.Drive_R3_Val.setText(_fmt(lg.round_times[2]))
        ui.Drive_total.setText(_fmt(lg.drive_total))

        # Rest_Next ใช้แสดง Camera status แล้ว ไม่ต้อง set ที่นี่

        self._apply_status(lg.status)

    def _apply_status(self, status: str):
        ui        = self.ui
        col, tint = _C[status]
        txt       = _STATUS_TEXT[status]

        ui.Driving_Status.setText(txt)
        ui.Driving_Status.setStyleSheet(f"color: {col}; font: 24pt 'Segoe UI';")
        self._center_status()

        frame_style = (f"background-color: {tint}; "
                       f"border: 1px solid {col}; border-radius: 4px;")
        ui.frame_2.setStyleSheet(f"QFrame#frame_2 {{ {frame_style} }}")
        ui.Status_frame.setStyleSheet(f"QFrame#Status_frame {{ {frame_style} }}")

    # ─── Face status ─────────────────────────────────────────
    def _on_face_detected(self):
        self.ui.label_23.setText("Camera :")
        self.ui.Rest_Next.setText("True")
        self.ui.Rest_Next.setStyleSheet("color: #00FF7F; font: 16pt 'Segoe UI';")

    def _on_face_lost(self):
        self.ui.label_23.setText("Camera :")
        self.ui.Rest_Next.setText("False")
        self.ui.Rest_Next.setStyleSheet("color: #FF3333; font: 16pt 'Segoe UI';")

    def _on_face_alert(self, msg: str):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(self, "แจ้งเตือน", msg)

    # ─── DB send ─────────────────────────────────────────────
    def _send_realtime(self):
        if not self._gps_fixed:
            return
        lat, lon, speed, status = self._last_pos
        lg = self.logic
        post_realtime(self.driver_id, TRUCK_ID,
                      lat, lon,
                      speed, status,
                      lg.elapsed_time, lg.stop_duration)

    # ─── cleanup ─────────────────────────────────────────────
    def closeEvent(self, event):
        db_close()
        self.worker.stop()
        self.face_monitor.stop()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)

    _main_window = None

    def on_login(driver_id, firstname, lastname):
        global _main_window
        _main_window = DriverApp(driver_id, firstname, lastname)
        _main_window.show()
        QTimer.singleShot(0, _main_window._center_widgets)

    login = LoginWindow()
    login.login_success.connect(on_login)
    login.show()

    sys.exit(app.exec())