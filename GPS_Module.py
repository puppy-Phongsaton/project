# -*- coding: utf-8 -*-
import time


def _is_rpi():
    try:
        with open("/proc/device-tree/model") as f:
            return "Raspberry Pi" in f.read()
    except Exception:
        return False


IS_RPI = _is_rpi()


class GPS:
    def __init__(self, port="/dev/ttyAMA0", baud=9600):
        if IS_RPI:
            import serial

            self.ser = serial.Serial(
                port,
                baudrate=baud,
                timeout=1
            )
            self._sim = False

        else:
            print("[GPS] Simulation mode")
            self.ser = None
            self._sim = True
            self._step = 0

    def read(self):
        """
        รับ raw NMEA จาก GPS
        คืนค่า bytes หรือ None
        """

        if self._sim:
            return self._sim_read()

        line = self.ser.readline()

        if not line:
            return None

        return line

    def close(self):
        if self.ser is not None:
            self.ser.close()

    # ---------------------------------------------------------
    # Simulator
    # ---------------------------------------------------------

    def _sim_read(self):
        time.sleep(1)

        self._step += 1

        speed_knots = (20 + (self._step % 5)) / 1.852

        lat_dd = 14.0 + self._step * 0.0001
        lon_dd = 100.0 + self._step * 0.0001

        now = time.strftime("%H%M%S")
        day = time.strftime("%d%m%y")

        sentence = (
            f"$GPRMC,{now},A,"
            f"{self._dd_to_nmea(lat_dd, 2)},N,"
            f"{self._dd_to_nmea(lon_dd, 3)},E,"
            f"{speed_knots:.2f},0.00,"
            f"{day},,"
        )

        checksum = self._checksum(sentence[1:])

        return f"{sentence}*{checksum}\r\n".encode()

    @staticmethod
    def _dd_to_nmea(dd, digits):
        deg = int(dd)
        minutes = (dd - deg) * 60

        return f"{deg:0{digits}d}{minutes:07.4f}"

    @staticmethod
    def _checksum(data):
        checksum = 0

        for char in data:
            checksum ^= ord(char)

        return f"{checksum:02X}"