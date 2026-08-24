# -*- coding: utf-8 -*-
import time
import threading
from PySide6.QtCore import QThread, Signal

from GPS_Module import GPS


class GpsWorker(QThread):
    data_ready = Signal(float, float, float, str, str)
    no_fix     = Signal()   # ??? GPS ????????? fix (V)
    no_gps     = Signal()   # ?????????????????? GPS ???

    def __init__(self, port="/dev/ttyAMA0", baud=9600, parent=None):
        super().__init__(parent)
        self._running    = True
        self._force_stop = threading.Event()
        self._gps        = GPS(port=port, baud=baud)

    @property
    def force_stop(self):
        return self._force_stop.is_set()

    @force_stop.setter
    def force_stop(self, value: bool):
        if value:
            self._force_stop.set()
        else:
            self._force_stop.clear()

    def stop(self):
        self._running = False
        self.wait()

    def run(self):
        while self._running:
            raw = self._gps.read()

            if not raw:                  # ??????????????????
                self.no_gps.emit()
                time.sleep(0.05)
                continue

            try:
                parts = raw.decode("utf-8", errors="replace").strip().split(",")
                if parts[0] != "$GPRMC":
                    continue

                if parts[2] == "A":      # fix valid
                    lat   = int(parts[3][:2]) + float(parts[3][2:]) / 60
                    lon   = int(parts[5][:3]) + float(parts[5][3:]) / 60
                    speed = float(parts[7]) * 1.852 if parts[7] else 0.0

                    if self._force_stop.is_set():
                        speed = 0.0

                    t_str = f"{parts[1][0:2]}:{parts[1][2:4]}:{parts[1][4:6]}"
                    d_str = f"{parts[9][0:2]}/{parts[9][2:4]}/{parts[9][4:6]}"
                    self.data_ready.emit(lat, lon, speed, t_str, d_str)

                else:                    # ??? GPS ?????? no fix (V)
                    self.no_fix.emit()

            except Exception as e:
                print(f"[GPS ERROR] {e}")