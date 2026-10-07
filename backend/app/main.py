from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlmodel import SQLModel, select

from app.db import engine, get_session
from app.domain import (
    RuleError,
    active_cert,
    assert_can_set_status,
    assert_melt_temp,
    latest_peak,
)
from app.models import CookLog, Kettle, MeltCert, User, Workshop, utcnow
from app.security import make_token, parse_token, verify_password
from app.seed import seed_demo


async def current_user(request: Request) -> User | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    username = parse_token(header.split(" ", 1)[1])
    if not username:
        return None
    with get_session() as session:
        return session.exec(select(User).where(User.username == username)).first()


def load_kettle(session, kettle_id: int) -> Kettle | None:
    return session.exec(
        select(Kettle)
        .where(Kettle.id == kettle_id)
        .options(selectinload(Kettle.cooks), selectinload(Kettle.melt_certs))
    ).first()


def cert_json(cert: MeltCert) -> dict:
    return {
        "id": cert.id,
        "kettleId": cert.kettle_id,
        "certNo": cert.cert_no,
        "meltTempC": cert.melt_temp_c,
        "issuedBy": cert.issued_by,
        "issuedAt": cert.issued_at.isoformat() if cert.issued_at else None,
        "usedAt": cert.used_at.isoformat() if cert.used_at else None,
        "usedBy": cert.used_by or None,
    }


def active_cert_of(kettle: Kettle) -> MeltCert | None:
    actives = [c for c in (kettle.melt_certs or []) if c.used_at is None]
    if not actives:
        return None
    return min(actives, key=lambda c: c.cert_no)


def kettle_json(kettle: Kettle) -> dict:
    cert = active_cert_of(kettle)
    return {
        "id": kettle.id,
        "code": kettle.code,
        "status": kettle.status,
        "bench": kettle.bench,
        "latestPeakC": latest_peak(kettle),
        "cookCount": len(kettle.cooks or []),
        "activeCertNo": cert.cert_no if cert else None,
    }


async def health(request: Request):
    return JSONResponse({"status": "ok", "service": "GlueKettle"})


async def login(request: Request):
    body = await request.json()
    with get_session() as session:
        user = session.exec(select(User).where(User.username == body.get("username", ""))).first()
        if user is None or not verify_password(body.get("password", ""), user.password_hash):
            return JSONResponse({"detail": "用户名或密码错误"}, status_code=401)
        return JSONResponse(
            {"access_token": make_token(user.username), "user": {"username": user.username, "role": user.role}}
        )


async def me(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    return JSONResponse({"username": user.username, "role": user.role})


async def board(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    with get_session() as session:
        shop = session.exec(select(Workshop)).first()
        if shop is None:
            return JSONResponse({"detail": "尚无熬胶坊"}, status_code=404)
        kettles = session.exec(
            select(Kettle)
            .where(Kettle.workshop_id == shop.id)
            .options(selectinload(Kettle.cooks), selectinload(Kettle.melt_certs))
        ).all()
        loaded = sorted(kettles, key=lambda k: k.bench)
        return JSONResponse(
            {"workshop": shop.name, "alley": shop.alley, "kettles": [kettle_json(k) for k in loaded]}
        )


async def add_cook(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = int(request.path_params["kettle_id"])
    body = await request.json()
    try:
        peak = float(body.get("peakTempC"))
    except (TypeError, ValueError):
        return JSONResponse({"detail": "峰值温度必须是数字"}, status_code=400)
    with get_session() as session:
        kettle = load_kettle(session, kettle_id)
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        # 登记峰值前必须读到本锅未核销溶化证；没有则整笔拒绝，峰值不得先入库。
        cert = active_cert(session, kettle.id)
        if cert is None:
            return JSONResponse({"detail": "该锅没有未核销溶化证，不能登记峰值"}, status_code=400)
        session.add(CookLog(kettle_id=kettle.id, peak_temp_c=peak, operator=user.username))
        session.commit()
        kettle = load_kettle(session, kettle_id)
        return JSONResponse(kettle_json(kettle))


async def set_status(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = int(request.path_params["kettle_id"])
    body = await request.json()
    with get_session() as session:
        kettle = load_kettle(session, kettle_id)
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        try:
            # 改锅态不看溶化证。
            assert_can_set_status(kettle, body.get("status", ""))
        except RuleError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        kettle.status = body.get("status")
        session.add(kettle)
        session.commit()
        kettle = load_kettle(session, kettle_id)
        return JSONResponse(kettle_json(kettle))


async def list_certs(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = int(request.path_params["kettle_id"])
    with get_session() as session:
        if load_kettle(session, kettle_id) is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        certs = session.exec(
            select(MeltCert)
            .where(MeltCert.kettle_id == kettle_id)
            .order_by(MeltCert.cert_no.desc(), MeltCert.id.desc())
        ).all()
        return JSONResponse({"certs": [cert_json(c) for c in certs]})


async def issue_cert(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = int(request.path_params["kettle_id"])
    body = await request.json()
    # 证号从 1 起，必须为正整数。
    try:
        cert_no = int(body.get("certNo"))
    except (TypeError, ValueError):
        return JSONResponse({"detail": "证号必须是整数"}, status_code=400)
    if cert_no < 1:
        return JSONResponse({"detail": "证号须从 1 起"}, status_code=400)
    try:
        melt_temp = float(body.get("meltTempC"))
    except (TypeError, ValueError):
        return JSONResponse({"detail": "溶化温度必须是数字"}, status_code=400)
    try:
        assert_melt_temp(melt_temp)
    except RuleError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    with get_session() as session:
        kettle = load_kettle(session, kettle_id)
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        cert = MeltCert(
            kettle_id=kettle.id,
            cert_no=cert_no,
            melt_temp_c=melt_temp,
            issued_by=user.username,
        )
        session.add(cert)
        try:
            session.commit()
        except IntegrityError:
            # 并发抢交同一证号：部分唯一索引只放行一张。
            session.rollback()
            return JSONResponse(
                {"detail": f"本锅证号 {cert_no} 已有未核销溶化证，不能重复开证"}, status_code=409
            )
        session.refresh(cert)
        return JSONResponse(cert_json(cert), status_code=201)


async def redeem_cert(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    # 核销归管理员。
    if user.role != "admin":
        return JSONResponse({"detail": "只有管理员可以核销溶化证"}, status_code=403)
    cert_id = int(request.path_params["cert_id"])
    with get_session() as session:
        cert = session.exec(select(MeltCert).where(MeltCert.id == cert_id)).first()
        if cert is None:
            return JSONResponse({"detail": "溶化证不存在"}, status_code=404)
        if cert.used_at is not None:
            return JSONResponse({"detail": "该溶化证已核销"}, status_code=400)
        cert.used_at = utcnow()
        cert.used_by = user.username
        session.add(cert)
        session.commit()
        session.refresh(cert)
        return JSONResponse(cert_json(cert))


def init() -> None:
    SQLModel.metadata.create_all(engine)
    seed_demo()


init()

app = Starlette(
    routes=[
        Route("/api/health", health),
        Route("/api/auth/login", login, methods=["POST"]),
        Route("/api/auth/me", me),
        Route("/api/board", board),
        Route("/api/kettles/{kettle_id:int}/cooks", add_cook, methods=["POST"]),
        Route("/api/kettles/{kettle_id:int}/status", set_status, methods=["POST"]),
        Route("/api/kettles/{kettle_id:int}/melt-certs", list_certs),
        Route("/api/kettles/{kettle_id:int}/melt-certs", issue_cert, methods=["POST"]),
        Route("/api/melt-certs/{cert_id:int}/redeem", redeem_cert, methods=["POST"]),
    ],
    middleware=[Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])],
)
