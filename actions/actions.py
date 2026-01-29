from __future__ import annotations
from typing import Any, Dict, List, Tuple

import math
import re
import sqlite3
from pathlib import Path
from datetime import datetime

from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet, FollowupAction


# =========================
# Utility functions
# =========================

def extract_numbers(text: str) -> List[float]:
    if not text:
        return []
    pattern = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
    nums = re.findall(pattern, text)
    out: List[float] = []
    for n in nums:
        try:
            out.append(float(n))
        except ValueError:
            pass
    return out


def stats(values: List[float]) -> Tuple[float, float, float]:
    n = len(values)
    if n == 0:
        return 0.0, 0.0, 0.0

    xbar = sum(values) / n
    if n < 2:
        return xbar, 0.0, 0.0

    var = sum((x - xbar) ** 2 for x in values) / (n - 1)
    s = math.sqrt(var)
    s_mean = s / math.sqrt(n)
    return xbar, s, s_mean


# =========================
# DB (SQLite)
# =========================

DB_PATH = Path(__file__).resolve().parent / "lab_data.db"

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS lab_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id TEXT NOT NULL,
        measurements_text TEXT,
        instrument_error REAL,
        created_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS measurements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL,
        value REAL NOT NULL,
        idx INTEGER NOT NULL,
        FOREIGN KEY(run_id) REFERENCES lab_runs(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL UNIQUE,
        n INTEGER,
        xbar REAL,
        s REAL,
        s_mean REAL,
        delta_stat REAL,
        delta_total REAL,
        rel_percent REAL,
        used_instr INTEGER,
        created_at TEXT NOT NULL,
        FOREIGN KEY(run_id) REFERENCES lab_runs(id)
    )
    """)

    conn.commit()
    conn.close()


def create_run(sender_id: str, measurements_text: str, instrument_error: float | None) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO lab_runs(sender_id, measurements_text, instrument_error, created_at) VALUES (?, ?, ?, ?)",
        (sender_id, measurements_text, instrument_error, datetime.utcnow().isoformat(timespec="seconds"))
    )
    run_id = cur.lastrowid
    conn.commit()
    conn.close()
    return int(run_id)


def insert_measurements(run_id: int, values: List[float]):
    conn = get_conn()
    cur = conn.cursor()
    cur.executemany(
        "INSERT INTO measurements(run_id, value, idx) VALUES (?, ?, ?)",
        [(run_id, float(v), i) for i, v in enumerate(values)]
    )
    conn.commit()
    conn.close()


def save_results(
    run_id: int,
    n: int,
    xbar: float,
    s: float,
    s_mean: float,
    delta_stat: float,
    delta_total: float,
    rel_percent: float,
    used_instr: bool
):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO results
        (run_id, n, xbar, s, s_mean, delta_stat, delta_total, rel_percent, used_instr, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        run_id, n, xbar, s, s_mean,
        delta_stat, delta_total, rel_percent,
        1 if used_instr else 0,
        datetime.utcnow().isoformat(timespec="seconds")
    ))
    conn.commit()
    conn.close()


# =========================
# Actions
# =========================

class ActionStoreMeasurements(Action):
    def name(self) -> str:
        return "action_store_measurements"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]):
        text = (tracker.latest_message.get("text", "") or "").strip()
        lower = text.lower()

        cut_idx = None
        for key in ["багаж", "төхөөрөмж", "масштаб"]:
            i = lower.find(key)
            if i != -1:
                cut_idx = i
                break

        meas_part = text if cut_idx is None else text[:cut_idx]
        instr_part = "" if cut_idx is None else text[cut_idx:]

        nums = extract_numbers(meas_part)
        if not nums:
            dispatcher.utter_message(text="Тоон хэмжилт олдсонгүй. Жишээ: 10.1 10.2 10.0 10.3")
            return []

        events = [SlotSet("measurements_text", meas_part.strip())]
        dispatcher.utter_message(
            text=f"Ойлголоо. {len(nums)} хэмжилт: {', '.join(str(x) for x in nums)}"
        )

        instr_nums = extract_numbers(instr_part)
        if instr_nums:
            instr = abs(instr_nums[0])
            events.append(SlotSet("instrument_error", instr))
            dispatcher.utter_message(text=f"Багажийн абсолют алдаа Δ_instr = {instr:g}")
            events.append(FollowupAction("action_calc_measurement_error"))
            return events

        dispatcher.utter_message(text="Багажийн алдааг оруулна уу (эсвэл 'алгас').")
        return events


class ActionStoreInstrumentError(Action):
    def name(self) -> str:
        return "action_store_instrument_error"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]):
        text = (tracker.latest_message.get("text", "") or "").strip().lower()

        if any(k in text for k in ["алгас", "skip", "мэдэхгүй", "байхгүй"]):
            dispatcher.utter_message(text="Багажийн алдааг алгаслаа.")
            return [
                SlotSet("instrument_error", None),
                FollowupAction("action_calc_measurement_error")
            ]

        nums = extract_numbers(text)
        if not nums:
            dispatcher.utter_message(text="Багажийн алдааны тоо олдсонгүй. Жишээ: 0.01")
            return []

        instr = abs(nums[0])
        dispatcher.utter_message(text=f"Δ_instr = {instr:g}")
        dispatcher.utter_message(text="Тооцооллыг эхлүүлж байна…")

        return [
            SlotSet("instrument_error", instr),
            FollowupAction("action_calc_measurement_error")
        ]


class ActionCalcMeasurementError(Action):
    def name(self) -> str:
        return "action_calc_measurement_error"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]):
        meas_text = tracker.get_slot("measurements_text") or ""
        values = extract_numbers(meas_text)

        if not values:
            dispatcher.utter_message(text="Хэмжилтийн утга алга.")
            return []

        n = len(values)
        xbar, s, s_mean = stats(values)
        delta_stat = s_mean

        instr = tracker.get_slot("instrument_error")
        used_instr = False
        delta_total = delta_stat
        instr_f = None

        if instr is not None:
            try:
                instr_f = float(instr)
                delta_total = math.sqrt(delta_stat**2 + instr_f**2)
                used_instr = True
            except Exception:
                instr_f = None

        rel_percent = abs(delta_total / xbar) * 100 if xbar != 0 else 0.0

        def fmt(x: float) -> str:
            return f"{x:.6g}"

        msg = [
            "📌 **Хэмжилтийн алдаа – үр дүн**",
            f"- n = {n}",
            f"- x̄ = {fmt(xbar)}",
            f"- s = {fmt(s)}",
            f"- s/√n = {fmt(s_mean)}",
            f"- Δ_stat = {fmt(delta_stat)}"
        ]

        if used_instr:
            msg.append(f"- Δ_instr = {fmt(instr_f)}")
            msg.append(f"- Δ = {fmt(delta_total)}")
        else:
            msg.append(f"- Δ = {fmt(delta_total)} (багажийн алдаагүй)")

        msg.append(f"- ε = {fmt(rel_percent)} %")
        msg.append(f"✅ **Хариу:** x = {fmt(xbar)} ± {fmt(delta_total)}")

        try:
            init_db()
            run_id = create_run(tracker.sender_id, meas_text, instr_f)
            insert_measurements(run_id, values)
            save_results(
                run_id, n, xbar, s, s_mean,
                delta_stat, delta_total, rel_percent, used_instr
            )
        except Exception as e:
            msg.append(f"⚠️ DB алдаа: {e}")

        dispatcher.utter_message(text="\n".join(msg))
        return []


class ActionResetCalc(Action):
    def name(self) -> str:
        return "action_reset_calc"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]):
        dispatcher.utter_message(text="Шинэ тооцоолол эхэллээ ✅")
        return [
            SlotSet("measurements_text", None),
            SlotSet("instrument_error", None)
        ]