# -*- coding: utf-8 -*-
"""
datapost.py
ส่งข้อมูลขึ้น InfluxDB ผ่าน influxdb-client
"""

import os

from influxdb_client import InfluxDBClient, WriteOptions
from influxdb_client.client.write_api import SYNCHRONOUS
from datetime import datetime

# ═══════════════════ CONFIG ═══════════════════════════════════
INFLUX_BUCKET = "project_truck_tracking_system"
INFLUX_URL    = os.getenv("INFLUX_URL")
INFLUX_TOKEN  = os.getenv("INFLUX_TOKEN")
INFLUX_ORG    = os.getenv("INFLUX_ORG")
# ═══════════════════ CLIENT ═══════════════════════════════════
_client    = None
_write_api = None


def _get_write_api():
    global _client, _write_api
    if _write_api is None:
        _client    = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
        _write_api = _client.write_api(write_options=SYNCHRONOUS)
    return _write_api
 
 
# ═══════════════════ POST FUNCTIONS ═══════════════════════════
 
def post_realtime(driver_id: str, truck_id: str,
                  lat: float, lon: float,
                  speed: float,
                  status: int,
                  drive_duration: float,
                  rest_duration: float):
    """
    Measurement: realtime
    ส่งทุก 5 วินาที
    """
    try:
        api = _get_write_api()
        record = {
            "measurement": "Realtimes",
            "tags": {
                "driver_ID": driver_id,
                "truck_ID":  truck_id,
            },
            "fields": {
                "latitude":       round(lat, 6),
                "longitude":      round(lon, 6),
                "speed":          round(speed, 2),
                "status":         int(status),
                "drive_duration": round(drive_duration, 1),
                "rest_duration":  round(rest_duration, 1),
            },
            "time": datetime.utcnow(),
        }
        api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=record)
        print(f"[DB-RT] driver={driver_id} truck={truck_id} "
              f"lat={lat:.5f} lon={lon:.5f} speed={speed:.1f} status={status} "
              f"drive={drive_duration:.1f}s rest={rest_duration:.1f}s")
    except Exception as e:
        print(f"[DB-RT ERROR] {e}")
 
 
def post_trigger(driver_id: str, truck_id: str,
                 drive_duration: float,
                 rest_duration: float,
                 rest_start: datetime,
                 rest_end: datetime):
    """
    Measurement: trigger
    ส่งเมื่อพักครบรอบแล้วกลับมาขับ
    """
    try:
        api = _get_write_api()
        record = {
            "measurement": "trigger",
            "tags": {
                "driver_ID": driver_id,
                "truck_ID":  truck_id,
            },
            "fields": {
                "drive_duration": round(drive_duration, 1),
                "rest_duration":  round(rest_duration, 1),
                "rest_start":     rest_start.isoformat(),
                "rest_end":       rest_end.isoformat(),
            },
            "time": datetime.utcnow(),
        }
        api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=record)
        print(f"[DB-TRIGGER] driver={driver_id} truck={truck_id} "
              f"drive={drive_duration:.1f}s rest={rest_duration:.1f}s "
              f"rest_start={rest_start.strftime('%H:%M:%S')} rest_end={rest_end.strftime('%H:%M:%S')}")
    except Exception as e:
        print(f"[DB-TRIGGER ERROR] {e}")
 
 
def close():
    """ปิด connection เมื่อปิดโปรแกรม"""
    global _client, _write_api
    if _write_api:
        _write_api.close()
    if _client:
        _client.close()
    _client    = None
    _write_api = None
 