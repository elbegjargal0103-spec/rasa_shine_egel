from __future__ import annotations
from typing import Any, Dict, List, Tuple

import math
import re

from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet, FollowupAction


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

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]):
        text = (tracker.latest_message.get("text", "") or "").strip()
        lower = text.lower()

        # "багаж/төхөөрөмж/масштаб" гэдгийг олж, өмнөхийг хэмжилт, хойшихыг багажийн алдаа гэж салгана
        cut_idx = None
        for key in ["багаж", "төхөөрөмж", "масштаб"]:
            i = lower.find(key)
            if i != -1:
                cut_idx = i
                break

        meas_part = text if cut_idx is None else text[:cut_idx]
        instr_part = "" if cut_idx is None else text[cut_idx:]

        nums = extract_numbers(meas_part)
        if len(nums) < 1:
            dispatcher.utter_message(text="Тоон хэмжилт олдсонгүй. Жишээ: 10.1 10.2 10.0 10.3")
            return []

        events = [SlotSet("measurements_text", meas_part.strip())]
        dispatcher.utter_message(
            text=f"Ойлголоо. {len(nums)} хэмжилтийн утга авлаа: {', '.join(str(x) for x in nums)}"
        )

        # нэг мөрөнд багажийн алдаа байвал шууд сетлээд бодно
        instr_nums = extract_numbers(instr_part)
        if instr_nums:
            instr = abs(instr_nums[0])
            events.append(SlotSet("instrument_error", instr))
            dispatcher.utter_message(text=f"Багажийн абсолют алдаа Δ_instr = {instr:g} гэж авлаа.")
            events.append(FollowupAction("action_calc_measurement_error"))
            return events

        # байхгүй бол дараагийн алхамд асууна
        return events


class ActionStoreInstrumentError(Action):
    def name(self) -> str:
        return "action_store_instrument_error"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]):
        text = (tracker.latest_message.get("text", "") or "").strip().lower()

        if any(k in text for k in ["алгас", "skip", "мэдэхгүй", "байхгүй"]):
            dispatcher.utter_message(text="За ойлголоо. Багажийн алдааг алгаслаа.")
            return [SlotSet("instrument_error", None), FollowupAction("action_calc_measurement_error")]

        nums = extract_numbers(text)
        if len(nums) < 1:
            dispatcher.utter_message(text="Багажийн алдааны тоон утга олдсонгүй. Жишээ: 'багажийн алдаа 0.01'")
            return []

        instr = abs(nums[0])
        dispatcher.utter_message(text=f"Багажийн абсолют алдаа Δ_instr = {instr:g} гэж авлаа.")
        return [SlotSet("instrument_error", instr), FollowupAction("action_calc_measurement_error")]


class ActionCalcMeasurementError(Action):
    def name(self) -> str:
        return "action_calc_measurement_error"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]):
        meas_text = tracker.get_slot("measurements_text") or ""
        values = extract_numbers(meas_text)

        if len(values) < 1:
            dispatcher.utter_message(text="Хэмжилтийн утга алга байна. Эхлээд хэмжилтүүдээ явуулна уу.")
            return []

        n = len(values)
        xbar, s, s_mean = stats(values)
        delta_stat = s_mean

        instr = tracker.get_slot("instrument_error")
        used_instr = False
        delta_total = delta_stat

        if instr is not None:
            try:
                instr_f = float(instr)
                delta_total = math.sqrt(delta_stat**2 + instr_f**2)
                used_instr = True
            except (TypeError, ValueError):
                pass

        rel_percent = abs(delta_total / xbar) * 100.0 if xbar != 0 else 0.0

        def fmt(x: float) -> str:
            return f"{x:.6g}"

        msg = []
        msg.append("📌 **Хэмжилтийн алдаа боловсруулалтын үр дүн**")
        msg.append(f"- n = {n}")
        msg.append(f"- Дундаж утга x̄ = {fmt(xbar)}")
        msg.append(f"- Стандарт хазайлт s = {fmt(s)}")
        msg.append(f"- Дундажийн стандарт алдаа s/√n = {fmt(s_mean)}")
        msg.append(f"- Статистик абсолют алдаа Δ_stat = {fmt(delta_stat)}")

        if used_instr:
            msg.append(f"- Багажийн алдаа Δ_instr = {fmt(float(instr))}")
            msg.append(f"- Нийлмэл абсолют алдаа Δ = √(Δ_stat² + Δ_instr²) = {fmt(delta_total)}")
        else:
            msg.append(f"- Нийт абсолют алдаа Δ = {fmt(delta_total)} (багажийн алдааг оруулаагүй)")

        msg.append(f"- Харьцангуй алдаа ε = {fmt(rel_percent)} %")
        msg.append(f"✅ **Эцсийн хариу:** x = {fmt(xbar)} ± {fmt(delta_total)}")
        msg.append("♻️ Дахин шинээр тооцоо хийх бол: 'дахин' гэж бичээрэй.")

        dispatcher.utter_message(text="\n".join(msg))
        return []


class ActionResetCalc(Action):
    def name(self) -> str:
        return "action_reset_calc"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]):
        dispatcher.utter_message(text="За, шинэ тооцоолол эхлүүлье ✅")
        return [SlotSet("measurements_text", None), SlotSet("instrument_error", None)]
