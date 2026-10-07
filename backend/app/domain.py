"""熬锅规则：出胶只认最近峰值 ≥ 90℃；溶化证温度须 ≥ 70℃。"""

from sqlmodel import select

from app.models import Kettle, MeltCert

MIN_PEAK = 90.0
MIN_MELT_TEMP = 70.0


class RuleError(ValueError):
    pass


def latest_peak(kettle: Kettle) -> float | None:
    if not kettle.cooks:
        return None
    latest = max(kettle.cooks, key=lambda c: c.taken_at)
    return latest.peak_temp_c


def active_cert(session, kettle_id: int) -> MeltCert | None:
    """该锅现行（未核销）溶化证。"""
    return session.exec(
        select(MeltCert)
        .where(MeltCert.kettle_id == kettle_id, MeltCert.used_at.is_(None))
        .order_by(MeltCert.cert_no)
    ).first()


def assert_melt_temp(value: float) -> None:
    if value != value or value in (float("inf"), float("-inf")):
        raise RuleError("溶化温度必须是数字")
    if value <= 0:
        raise RuleError("溶化温度须为正数")
    if value < MIN_MELT_TEMP:
        raise RuleError(f"溶化温度 {value:g}℃ 低于 {MIN_MELT_TEMP:.0f}℃，不能开证")


def assert_can_set_status(kettle: Kettle, new_status: str) -> None:
    allowed = {Kettle.STATUS_COLD, Kettle.STATUS_BOILING, Kettle.STATUS_DRAWN}
    if new_status not in allowed:
        raise RuleError(f"无效状态：{new_status}")
    # 改锅态不看溶化证；已出胶仍只认峰值门槛。
    if new_status != Kettle.STATUS_DRAWN:
        return
    peak = latest_peak(kettle)
    if peak is None:
        raise RuleError("该锅尚无煮胶峰值，不能出胶")
    if peak < MIN_PEAK:
        raise RuleError(f"最近峰值 {peak}℃ 低于 {MIN_PEAK:.0f}℃，不能出胶")
