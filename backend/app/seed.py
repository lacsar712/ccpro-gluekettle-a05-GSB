from sqlmodel import select

from app.db import get_session
from app.models import CookLog, Kettle, MeltCert, User, Workshop
from app.security import hash_password


# (锅号, 台位, 初始状态, 历史最近峰值, 现行溶化证(证号, 温度) 或 None)
# 锅-5 一口锅零张溶化证：登峰值应被整笔拒绝。
LAYOUT = [
    ("锅-1", 0, Kettle.STATUS_BOILING, 96.0, (1, 88.0)),
    ("锅-2", 1, Kettle.STATUS_COLD, None, (1, 75.5)),
    ("锅-3", 2, Kettle.STATUS_DRAWN, 102.0, None),
    ("锅-4", 3, Kettle.STATUS_BOILING, 82.0, (2, 91.0)),
    ("锅-5", 4, Kettle.STATUS_COLD, None, None),
    ("锅-6", 5, Kettle.STATUS_DRAWN, 94.0, None),
]


def seed_demo() -> None:
    with get_session() as session:
        admin = session.exec(select(User).where(User.username == "admin")).first()
        if admin is None:
            session.add(User(username="admin", password_hash=hash_password("123456"), role="admin"))
        else:
            admin.password_hash = hash_password("123456")
            admin.role = "admin"
        worker = session.exec(select(User).where(User.username == "worker")).first()
        if worker is None:
            session.add(User(username="worker", password_hash=hash_password("123456"), role="worker"))
        else:
            worker.password_hash = hash_password("123456")
            worker.role = "worker"
        session.flush()

        shop = session.exec(select(Workshop)).first()
        if shop is None:
            shop = Workshop(name="骨巷熬胶坊", alley="西市骨巷")
            session.add(shop)
            session.flush()

        # 幂等回填：旧数据卷升级时补齐锅位、历史峰值与溶化证，不覆盖既有业务数据。
        for code, bench, status, peak, cert in LAYOUT:
            kettle = session.exec(select(Kettle).where(Kettle.code == code)).first()
            if kettle is None:
                kettle = Kettle(workshop_id=shop.id, code=code, status=status, bench=bench)
                session.add(kettle)
                session.flush()
            if peak is not None and not session.exec(
                select(CookLog).where(CookLog.kettle_id == kettle.id)
            ).first():
                session.add(CookLog(kettle_id=kettle.id, peak_temp_c=peak, operator="worker"))
            if cert is not None and not session.exec(
                select(MeltCert).where(MeltCert.kettle_id == kettle.id)
            ).first():
                cert_no, melt_temp = cert
                session.add(
                    MeltCert(
                        kettle_id=kettle.id,
                        cert_no=cert_no,
                        melt_temp_c=melt_temp,
                        issued_by="worker",
                    )
                )
        session.commit()
