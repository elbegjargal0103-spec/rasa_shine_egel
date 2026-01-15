from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple

import math
import re

from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet


def extract_numbers(text: str) -> List[float]:
    """
    Extract floats/ints from a string.
    Accepts separators: space, comma, semicolon, etc.
    """
    if not text:
        return []
    # Matches: -12, 3.14, .5, 1., 1e-3, -2.5E6
    pattern = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
    nums = re.findall(pattern, text)
    out = []
    for n in nums:
        try:
            out.append(float(n))
        except ValueError:
            pass
    return outS


def stats(values: List[float]) -> Tuple[float, float, float]:
    """
    Returns:
      mean xbar
      sample std dev s (n-1)
      standard error of mean s_mean = s/sqrt(n)
    """
    n = len(values)
    xbar = sum(values) / n
    if n < 2:
        return xbar, 0.0, 0.0
    var = sum((x - xbar) ** 2 for x in values) / (n - 1)
    s = math.sqrt(var)
    s_mean = s / math.sqrt(n)
    return xbar, s, s_mean


class ActionStoreMeasurements(Action):
    def name(self) -> str:
        return "action_store_measurements"

    def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        text = tracker.latest_message.get("text", "")
        nums = extract_numbers(text)

        if len(nums) < 1:
            dispatcher.utter_message(
                text="Тоон утга олдсонгүй. Хэмжилтүүдээ жишээ шиг бичээд явуулна уу: 10.1 10.2 10.0 10.3"
            )
            return []

        # store original text (so user can see what was used)
        dispatcher.utter_message(
            text=f"Ойлголоо. {len(nums)} хэмжилтийн утга авлаа: {', '.join(str(x) for x in nums)}"
        )
        return [SlotSet("measurements_text", text)]


class ActionStoreInstrumentError(Action):
    def name(self) -> str:
        return "action_store_instrument_error"

    def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        text = tracker.latest_message.get("text", "")

        # Allow skip keywords
        if any(k in text.lower() for k in ["алгас", "skip", "мэдэхгүй", "байхгүй"]):
            dispatcher.utter_message(text="За ойлголоо. Багажийн алдааг алгаслаа.")
            return [SlotSet("instrument_error", None)]

        nums = extract_numbers(text)
        if len(nums) < 1:
            dispatcher.utter_message(
                text="Багажийн алдааны тоон утга олдсонгүй. Жишээ: 'багажийн алдаа 0.01' гэж бичнэ үү."
            )
            return []

        instr = abs(nums[0])
        dispatcher.utter_message(text=f"Багажийн абсолют алдаа Δ_instr = {instr:g} гэж авлаа.")
        return [SlotSet("instrument_error", instr)]


class ActionCalcMeasurementError(Action):
    def name(self) -> str:
        return "action_calc_measurement_error"

    def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        meas_text = tracker.get_slot("measurements_text") or ""
        values = extract_numbers(meas_text)

        if len(values) < 1:
            dispatcher.utter_message(
                text="Хэмжилтийн утга алга байна. Эхлээд хэмжилтүүдээ явуулна уу (ж: 10.1 10.2 10.0 10.3)."
            )
            return []

        n = len(values)
        xbar, s, s_mean = stats(values)

        # Δ_stat: энд бид дундажийн стандарт алдааг авлаа (s/√n).
        # Зарим лабораторид t* s/√n (confidence interval) хэрэглэдэг — хүсвэл нэмнэ.
        delta_stat = s_mean

        instr = tracker.get_slot("instrument_error")
        delta_total = delta_stat
        used_instr = False

        if instr is not None:
            try:
                instr_f = float(instr)
                delta_total = math.sqrt(delta_stat**2 + instr_f**2)
                used_instr = True
            except (TypeError, ValueError):
                pass

        rel_percent = 0.0
        if xbar != 0:
            rel_percent = abs(delta_total / xbar) * 100.0

        # Nice formatting
        def fmt(x: float) -> str:
            # 6 significant-ish
            return f"{x:.6g}"

        msg_lines = []
        msg_lines.append("📌 **Хэмжилтийн алдаа боловсруулалтын үр дүн**")
        msg_lines.append(f"- n = {n}")
        msg_lines.append(f"- Дундаж утга x̄ = {fmt(xbar)}")
        msg_lines.append(f"- Стандарт хазайлт s = {fmt(s)}")
        msg_lines.append(f"- Дундажийн стандарт алдаа s/√n = {fmt(s_mean)}")
        msg_lines.append(f"- Статистик абсолют алдаа Δ_stat = {fmt(delta_stat)}")

        if used_instr:
            msg_lines.append(f"- Багажийн алдаа Δ_instr = {fmt(float(instr))}")
            msg_lines.append(f"- Нийлмэл абсолют алдаа Δ = √(Δ_stat² + Δ_instr²) = {fmt(delta_total)}")
        else:
            msg_lines.append(f"- Нийт абсолют алдаа Δ = {fmt(delta_total)} (багажийн алдааг оруулаагүй)")

        msg_lines.append(f"- Харьцангуй алдаа ε = {fmt(rel_percent)} %")
        msg_lines.append("")
        msg_lines.append(f"✅ **Эцсийн хариу:** x = {fmt(xbar)} ± {fmt(delta_total)}")

        dispatcher.utter_message(text="\n".join(msg_lines))
        return []
