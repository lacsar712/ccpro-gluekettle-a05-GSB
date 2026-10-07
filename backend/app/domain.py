"""熬锅规则。

- 溶化证：溶化温度须为正数且不低于 70℃。
- 登记煮胶峰值：该锅必须存在一张未核销溶化证，否则整笔拒绝。
- 出胶门槛：不看溶化证，只认最近一次煮胶峰值须 ≥ 90℃。
"""

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
    """该锅现行（未核销）溶化证；一口锅至多一张。"""
    return session.exec(
        select(MeltCert)
        .where(MeltCert.kettle_id == kettle_id, MeltCert.revoked_at.is_(None))
        .order_by(MeltCert.cert_no.desc())
    ).first()


def assert_melt_temp(value: float) -> None:
    if value != value or value in (float("inf"), float("-inf")):
        raise RuleError("溶化温度必须是数字")
    if value <= 0:
        raise RuleError("溶化温度必须为正数")
    if value < MIN_MELT_TEMP:
        raise RuleError(f"溶化温度 {value:g}℃ 低于 {MIN_MELT_TEMP:.0f}℃，不能开证")


def next_cert_no(session, kettle_id: int) -> int:
    rows = session.exec(select(MeltCert).where(MeltCert.kettle_id == kettle_id)).all()
    if not rows:
        return 1
    return max(c.cert_no for c in rows) + 1


def assert_can_log_peak(session, kettle_id: int) -> None:
    """峰值登记前置门：无未核销溶化证则拒绝，峰值不得先入库。"""
    if active_cert(session, kettle_id) is None:
        raise RuleError("该锅没有未核销溶化证，不能登记峰值")


def assert_can_set_status(kettle: Kettle, new_status: str) -> None:
    allowed = {Kettle.STATUS_COLD, Kettle.STATUS_BOILING, Kettle.STATUS_DRAWN}
    if new_status not in allowed:
        raise RuleError(f"无效状态：{new_status}")
    if new_status != Kettle.STATUS_DRAWN:
        return
    peak = latest_peak(kettle)
    if peak is None:
        raise RuleError("该锅尚无煮胶峰值，不能出胶")
    if peak < MIN_PEAK:
        raise RuleError(f"最近峰值 {peak}℃ 低于 {MIN_PEAK:.0f}℃，不能出胶")
