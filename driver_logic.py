# -*- coding: utf-8 -*-
"""
driver_logic.py
Pure driving-time state machine – no Qt, no GPS I/O.

กติกาทดสอบ:
- ขับต่อเนื่องสูงสุด 240 วินาที
- เตือนที่ 210 วินาที
- พัก >= 30 วินาที → commit รอบขับ
- พักรวม >= 180 วินาที → END OF WORK
- หลัง END OF WORK ต้องพักรวมให้ครบ 720 วินาที
  โดย 180 วินาทีแรกนับรวมแล้ว
- ดังนั้น 180s + อีก 540s = 720s → NEW DAY
"""

from datetime import datetime, timedelta
import json
import os


# ═══════════════════════ CONFIG ═══════════════════════════════

MAX_TIME      = 240       # วินาที – ขับต่อเนื่องสูงสุดต่อรอบ
ALMOST_TIME   = 210       # วินาที – เตือนก่อนถึง MAX_TIME
REST_TIME     = 30        # วินาที – พักถึงจุดนี้ถือว่าเป็นรอบพัก
END_WORK_REST = 180       # วินาที – พักรวมถึงจุดนี้ → END OF WORK
NEW_DAY_WAIT  = 720       # วินาที – พักรวมทั้งหมดถึงจุดนี้ → เริ่มวันใหม่
DAY_TOTAL_MAX = 600       # วินาที – ขับรวมสูงสุดต่อวัน
MIN_SPEED     = 1.5       # km/h
SPEED_SAMPLES = 5


# ═════════════════════════════════════════════════════════════
# DRIVER LOGIC
# ═════════════════════════════════════════════════════════════

class DriverLogic:

    def __init__(self):
        self.elapsed_time = 0.0

        # เวลาพักของรอบปัจจุบัน
        self.stop_duration = 0.0

        self.rest_start = None
        self.new_day_waited = 0.0
        self.drive_start = None

        self.max_logged = False
        self._round_committed = False

        self.round_times = [0.0, 0.0, 0.0]
        self.current_round = 0

        # True = END OF WORK แล้ว กำลังรอพักให้ครบ NEW_DAY_WAIT
        self.end_of_day = False

        self._speed_buffer = []
        self.speed = 0.0

        self.last_committed_drive = 0.0
        self.pending_rest_payload = None

    # ═════════════════════════════════════════════════════════
    # PROPERTIES
    # ═════════════════════════════════════════════════════════

    @property
    def drive_total(self):
        return sum(self.round_times)

    @property
    def rest_remaining(self):
        """
        เวลาพักที่เหลือก่อนเริ่มวันใหม่
        """
        if self.end_of_day:
            return max(
                0.0,
                NEW_DAY_WAIT - self.new_day_waited
            )

        return -1.0

    @property
    def status(self):

        if self.end_of_day:
            return "WAIT_NEW_DAY"

        if self.speed < MIN_SPEED:
            return "REST"

        if (
            self.drive_total >= DAY_TOTAL_MAX
            or self.elapsed_time >= MAX_TIME
        ):
            return "OVER"

        if self.elapsed_time >= ALMOST_TIME:
            return "WARN"

        return "DRIVING"

    # ═════════════════════════════════════════════════════════
    # SPEED SMOOTHING
    # ═════════════════════════════════════════════════════════

    def smooth_speed(self, raw: float) -> float:

        self._speed_buffer.append(raw)

        if len(self._speed_buffer) > SPEED_SAMPLES:
            self._speed_buffer.pop(0)

        self.speed = (
            sum(self._speed_buffer)
            / len(self._speed_buffer)
        )

        return self.speed

    # ═════════════════════════════════════════════════════════
    # MAIN TICK
    # ═════════════════════════════════════════════════════════

    def tick(self, delta: float, speed: float):

        self.speed = speed

        # =====================================================
        # WAIT NEW DAY
        # =====================================================

        if self.end_of_day:

            if speed < MIN_SPEED:

                # สำคัญ:
                # เวลาที่พักหลัง END OF WORK
                # ยังนับต่อจากเวลาพักเดิม
                self.new_day_waited += delta

                print(
                    f"[WAIT] "
                    f"{self.new_day_waited:.1f}/"
                    f"{NEW_DAY_WAIT:.1f}s "
                    f"remaining="
                    f"{max(0, NEW_DAY_WAIT - self.new_day_waited):.1f}s"
                )

                # =============================================
                # พักรวมครบ 12 นาที
                # =============================================

                if self.new_day_waited >= NEW_DAY_WAIT:

                    self._start_new_day()

                    # ยังไม่เริ่มขับ เพราะ speed ยัง 0
                    return

                return

            else:

                # ถ้าพยายามขับก่อนพักครบ 12 นาที
                print(
                    "[WAIT] ยังพักไม่ครบ "
                    f"{self.new_day_waited:.1f}/"
                    f"{NEW_DAY_WAIT:.1f}s"
                )

                return

        # =====================================================
        # DRIVING
        # =====================================================

        if speed >= MIN_SPEED:

            # ครบ 3 รอบแล้ว
            if self.current_round >= 3:
                return

            # ขับรวมถึง MAX ต่อวัน
            if self.drive_total >= DAY_TOTAL_MAX:

                self._end_of_work("DAY TOTAL MAX")
                return

            # -------------------------------------------------
            # กลับมาขับหลังจากพัก
            # -------------------------------------------------

            if self.rest_start is not None:

                self._write_rest_log()

                self.rest_start = None

                # พักครบ REST_TIME
                if self.stop_duration >= REST_TIME:

                    self._commit_round(
                        "MAX TIME"
                        if self.max_logged
                        else "REST"
                    )

                    self.elapsed_time = 0.0
                    self.max_logged = False
                    self._round_committed = False

                else:

                    # พักสั้น
                    # เอาเวลาพักกลับไปรวมกับ elapsed_time
                    self.elapsed_time += self.stop_duration
                    self._round_committed = False

                self.stop_duration = 0.0

            # เริ่มจับเวลา Driving
            if self.drive_start is None:
                self.drive_start = datetime.now()

            self.elapsed_time += delta

        # =====================================================
        # REST / STOP
        # =====================================================

        else:

            if (
                self.drive_start is not None
                or self.elapsed_time > 0
            ):

                # เริ่มพัก
                if self.rest_start is None:
                    self.rest_start = datetime.now()

                self.stop_duration += delta

                # =============================================
                # ครบ 3 นาที → END OF WORK
                # =============================================

                if self.stop_duration >= END_WORK_REST:

                    self._end_of_work(
                        "END OF WORK"
                    )

                    return

    # ═════════════════════════════════════════════════════════
    # COMMIT DRIVE ROUND
    # ═════════════════════════════════════════════════════════

    def _commit_round(self, reason: str):

        if self.elapsed_time <= 0:
            return

        self.last_committed_drive = self.elapsed_time

        if self.current_round < 3:

            self.round_times[
                self.current_round
            ] = self.elapsed_time

            self.current_round += 1

        self._write_log(reason)

        self.drive_start = None

    # ═════════════════════════════════════════════════════════
    # END OF WORK
    # ═════════════════════════════════════════════════════════

    def _end_of_work(self, reason="END OF WORK"):

        # -----------------------------------------------------
        # สำคัญมาก:
        # เก็บเวลาพักทั้งหมดก่อน reset
        # -----------------------------------------------------

        total_rest = self.stop_duration

        # -----------------------------------------------------
        # เขียน REST LOG
        # -----------------------------------------------------

        if self.rest_start is not None:

            self._write_rest_log()

            self.rest_start = None

        # -----------------------------------------------------
        # Commit รอบขับล่าสุด
        # -----------------------------------------------------

        if (
            self.elapsed_time > 0
            and not self.max_logged
        ):

            self._commit_round(reason)

        # -----------------------------------------------------
        # บันทึก END OF DAY
        #
        # ย้อนกลับไปยังจุดที่พักครบ 3 นาที
        # -----------------------------------------------------

        self._write_end_of_day(
            offset_sec=END_WORK_REST
        )

        # -----------------------------------------------------
        # RESET DRIVE STATE
        # -----------------------------------------------------

        self.elapsed_time = 0.0
        self.stop_duration = 0.0

        self.max_logged = False
        self._round_committed = False

        self.drive_start = None

        # -----------------------------------------------------
        # เข้า WAIT NEW DAY
        # -----------------------------------------------------

        self.end_of_day = True

        # -----------------------------------------------------
        # สำคัญที่สุด
        #
        # พัก 3 นาทีแรก "นับรวม" ใน 12 นาทีแล้ว
        #
        # ตัวอย่าง:
        # total_rest = 180
        #
        # new_day_waited = 180
        #
        # เหลือ 540 วินาที
        # -----------------------------------------------------

        self.new_day_waited = min(
            total_rest,
            NEW_DAY_WAIT
        )

        remaining = max(
            0.0,
            NEW_DAY_WAIT - self.new_day_waited
        )

        print(
            f"[END OF WORK] "
            f"rest={total_rest:.1f}s | "
            f"new_day_waited="
            f"{self.new_day_waited:.1f}s | "
            f"remaining="
            f"{remaining:.1f}s"
        )

    # ═════════════════════════════════════════════════════════
    # START NEW DAY
    # ═════════════════════════════════════════════════════════

    def _start_new_day(self):

        self.round_times = [
            0.0,
            0.0,
            0.0
        ]

        self.current_round = 0

        self.end_of_day = False

        self.new_day_waited = 0.0

        self.elapsed_time = 0.0
        self.stop_duration = 0.0

        self.drive_start = None
        self.rest_start = None

        self.max_logged = False
        self._round_committed = False

        self.last_committed_drive = 0.0
        self.pending_rest_payload = None

        print(
            "[NEW DAY] "
            "เริ่มนับวันใหม่"
        )

    # ═════════════════════════════════════════════════════════
    # REST LOG
    # ═════════════════════════════════════════════════════════

    def _write_rest_log(self):

        if self.rest_start is None:
            return

        end = datetime.now()

        duration = (
            end - self.rest_start
        ).total_seconds()

        line = (
            f"[REST] "
            f"{self.rest_start.strftime('%Y-%m-%d %H:%M:%S')} → "
            f"{end.strftime('%H:%M:%S')} | "
            f"{duration:.0f}s "
            f"({duration / 60:.1f} min)\n"
        )

        self.pending_rest_payload = {

            "rest_start":
                self.rest_start,

            "rest_end":
                end,

            "rest_duration":
                duration,

            "drive_duration":
                self.last_committed_drive,
        }

        print(line.strip())

        with open(
            "drive_log.txt",
            "a",
            encoding="utf-8"
        ) as f:

            f.write(line)

    # ═════════════════════════════════════════════════════════
    # DRIVE LOG
    # ═════════════════════════════════════════════════════════

    def _write_log(self, reason: str):

        if self.drive_start is None:
            return

        end = datetime.now()

        line = (
            f"[DRIVE] "
            f"{self.drive_start.strftime('%Y-%m-%d %H:%M:%S')} → "
            f"{end.strftime('%H:%M:%S')} | "
            f"{self.elapsed_time:.1f}s | "
            f"{reason}\n"
        )

        print(line.strip())

        with open(
            "drive_log.txt",
            "a",
            encoding="utf-8"
        ) as f:

            f.write(line)

    # ═════════════════════════════════════════════════════════
    # END OF DAY LOG
    # ═════════════════════════════════════════════════════════

    @staticmethod
    def _write_end_of_day(offset_sec=0):

        end_time = (
            datetime.now()
            - timedelta(seconds=offset_sec)
        )

        text = end_time.strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        print(
            "[END OF DAY]",
            text
        )

        with open(
            "end_of_day_log.txt",
            "a",
            encoding="utf-8"
        ) as f:

            f.write(text + "\n")


# ═════════════════════════════════════════════════════════════
# PERSISTENCE
# ═════════════════════════════════════════════════════════════

STATE_FILE = "driver_state.json"


def save_state(logic: DriverLogic):

    state = {

        "elapsed_time":
            logic.elapsed_time,

        "stop_duration":
            logic.stop_duration,

        "new_day_waited":
            logic.new_day_waited,

        "round_times":
            logic.round_times,

        "current_round":
            logic.current_round,

        "end_of_day":
            logic.end_of_day,

        "max_logged":
            logic.max_logged,

        "_round_committed":
            logic._round_committed,

        "drive_start":
            (
                logic.drive_start.isoformat()
                if logic.drive_start
                else None
            ),

        "rest_start":
            (
                logic.rest_start.isoformat()
                if logic.rest_start
                else None
            ),

        "saved_at":
            datetime.now().isoformat(),
    }

    with open(
        STATE_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2
        )


def load_state(logic: DriverLogic):

    if not os.path.exists(STATE_FILE):
        return

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            s = json.load(f)

        # =====================================================
        # OFFLINE TIME
        # =====================================================

        saved_at = datetime.fromisoformat(
            s["saved_at"]
        )

        offline_sec = (
            datetime.now() - saved_at
        ).total_seconds()

        print(
            f"[STATE] ดับเครื่องไป "
            f"{offline_sec:.0f} วิ "
            f"({offline_sec / 60:.1f} นาที)"
        )

        # =====================================================
        # RESTORE STATE
        # =====================================================

        logic.elapsed_time = s.get(
            "elapsed_time",
            0.0
        )

        logic.stop_duration = s.get(
            "stop_duration",
            0.0
        )

        logic.new_day_waited = s.get(
            "new_day_waited",
            0.0
        )

        logic.round_times = s.get(
            "round_times",
            [0.0, 0.0, 0.0]
        )

        logic.current_round = s.get(
            "current_round",
            0
        )

        logic.end_of_day = s.get(
            "end_of_day",
            False
        )

        logic.max_logged = s.get(
            "max_logged",
            False
        )

        logic._round_committed = s.get(
            "_round_committed",
            False
        )

        logic.drive_start = (
            datetime.fromisoformat(
                s["drive_start"]
            )
            if s.get("drive_start")
            else None
        )

        logic.rest_start = (
            datetime.fromisoformat(
                s["rest_start"]
            )
            if s.get("rest_start")
            else None
        )

        # =====================================================
        # OFFLINE WHILE WAITING NEW DAY
        # =====================================================

        if logic.end_of_day:

            # เวลาที่ดับเครื่องต้องนับรวมใน 12 นาที
            logic.new_day_waited += offline_sec

            logic.new_day_waited = min(
                logic.new_day_waited,
                NEW_DAY_WAIT
            )

            print(
                f"[STATE] WAIT NEW DAY "
                f"{logic.new_day_waited:.0f}/"
                f"{NEW_DAY_WAIT:.0f}s | "
                f"เหลือ "
                f"{max(0, NEW_DAY_WAIT - logic.new_day_waited):.0f}s"
            )

            # ถ้าระหว่างดับพักครบแล้ว
            if (
                logic.new_day_waited
                >= NEW_DAY_WAIT
            ):

                logic._start_new_day()

        # =====================================================
        # OFFLINE WHILE RESTING
        # =====================================================

        elif logic.rest_start is not None:

            logic.stop_duration += offline_sec

            print(
                f"[STATE] พักสะสม "
                f"{logic.stop_duration:.0f}s"
            )

            # -----------------------------------------------
            # พักครบ 3 นาที
            # -----------------------------------------------

            if (
                logic.stop_duration
                >= END_WORK_REST
            ):

                logic._end_of_work(
                    "END OF WORK (offline)"
                )

            # -----------------------------------------------
            # พักครบ 30 วินาที
            # -----------------------------------------------

            elif (
                logic.stop_duration >= REST_TIME
                and not logic._round_committed
            ):

                logic._commit_round(
                    "REST (offline)"
                )

                logic.elapsed_time = 0.0
                logic.max_logged = False
                logic._round_committed = True

        # =====================================================
        # OFFLINE WHILE DRIVING
        # =====================================================

        else:

            # ดับระหว่างขับ
            # ถือว่าเริ่มพักตั้งแต่เวลาที่ดับ
            logic.stop_duration += offline_sec

            logic.rest_start = saved_at
            logic.drive_start = None

            print(
                f"[STATE] ดับระหว่างขับ "
                f"→ พักสะสม "
                f"{logic.stop_duration:.0f}s"
            )

            # -----------------------------------------------
            # พักครบ 3 นาที
            # -----------------------------------------------

            if (
                logic.stop_duration
                >= END_WORK_REST
            ):

                logic._end_of_work(
                    "END OF WORK (offline)"
                )

            # -----------------------------------------------
            # พักครบ 30 วินาที
            # -----------------------------------------------

            elif (
                logic.stop_duration >= REST_TIME
                and not logic._round_committed
            ):

                logic._commit_round(
                    "REST (offline)"
                )

                logic.elapsed_time = 0.0
                logic.max_logged = False
                logic._round_committed = True

    except Exception as e:

        print(
            f"[STATE] โหลด state ไม่ได้: {e}"
        )