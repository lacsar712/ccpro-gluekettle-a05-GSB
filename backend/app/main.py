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
    assert_can_log_peak,
    assert_can_set_status,
    assert_melt_temp,
    latest_peak,
    next_cert_no,
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
        select(Kettle).where(Kettle.id == kettle_id).options(selectinload(Kettle.cooks))
    ).first()


def cert_json(cert: MeltCert) -> dict:
    return {
        "id": cert.id,
        "certNo": cert.cert_no,
        "meltTempC": cert.melt_temp_c,
        "issuer": cert.issuer,
        "issuedAt": cert.issued_at.isoformat(),
        "revokedAt": cert.revoked_at.isoformat() if cert.revoked_at else None,
        "revoker": cert.revoker or None,
    }


def kettle_json(kettle: Kettle, session=None) -> dict:
    current = active_cert(session, kettle.id) if session is not None else None
    return {
        "id": kettle.id,
        "code": kettle.code,
        "status": kettle.status,
        "bench": kettle.bench,
        "latestPeakC": latest_peak(kettle),
        "cookCount": len(kettle.cooks or []),
        "activeCert": cert_json(current) if current else None,
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
            .options(selectinload(Kettle.cooks))
        ).all()
        loaded = sorted(kettles, key=lambda k: k.bench)
        return JSONResponse(
            {"workshop": shop.name, "alley": shop.alley, "kettles": [kettle_json(k, session) for k in loaded]}
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
    if peak != peak or peak in (float("inf"), float("-inf")) or peak <= 0:
        return JSONResponse({"detail": "峰值温度必须为正数"}, status_code=400)
    with get_session() as session:
        kettle = load_kettle(session, kettle_id)
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        # 门控在同一事务内先查：无证则整笔拒绝，峰值绝不先入库。
        try:
            assert_can_log_peak(session, kettle.id)
        except RuleError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        session.add(CookLog(kettle_id=kettle.id, peak_temp_c=peak, operator=user.username))
        session.commit()
        kettle = load_kettle(session, kettle_id)
        return JSONResponse(kettle_json(kettle, session))


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
            # 改锅态不看溶化证；出胶仍只认最近峰值 ≥ 90℃。
            assert_can_set_status(kettle, body.get("status", ""))
        except RuleError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        kettle.status = body.get("status")
        session.add(kettle)
        session.commit()
        kettle = load_kettle(session, kettle_id)
        return JSONResponse(kettle_json(kettle, session))


async def list_certs(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    kettle_id = request.query_params.get("kettle_id")
    with get_session() as session:
        stmt = select(MeltCert)
        if kettle_id:
            try:
                stmt = stmt.where(MeltCert.kettle_id == int(kettle_id))
            except ValueError:
                return JSONResponse({"detail": "锅号无效"}, status_code=400)
        stmt = stmt.order_by(MeltCert.kettle_id, MeltCert.cert_no.desc())
        certs = session.exec(stmt).all()
        kettles = {k.id: k.code for k in session.exec(select(Kettle)).all()}
        return JSONResponse(
            {"certs": [{**cert_json(c), "kettleId": c.kettle_id, "kettleCode": kettles.get(c.kettle_id)} for c in certs]}
        )


async def issue_cert(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    # 操作工可开证（管理员同样可开）。
    if user.role not in ("worker", "admin"):
        return JSONResponse({"detail": "无权开证"}, status_code=403)
    body = await request.json()
    try:
        kettle_id = int(body.get("kettleId"))
        melt_temp = float(body.get("meltTempC"))
    except (TypeError, ValueError):
        return JSONResponse({"detail": "锅号与溶化温度必须是数字"}, status_code=400)
    try:
        assert_melt_temp(melt_temp)
    except RuleError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    with get_session() as session:
        kettle = session.exec(select(Kettle).where(Kettle.id == kettle_id)).first()
        if kettle is None:
            return JSONResponse({"detail": "锅不存在"}, status_code=404)
        if active_cert(session, kettle_id) is not None:
            return JSONResponse({"detail": "该锅已有未核销溶化证，先核销再开新证"}, status_code=400)
        cert_no = next_cert_no(session, kettle_id)
        cert = MeltCert(
            kettle_id=kettle_id,
            cert_no=cert_no,
            melt_temp_c=melt_temp,
            issuer=user.username,
        )
        session.add(cert)
        try:
            session.commit()
        except IntegrityError:
            # 两名操作工几乎同时抢交同一证号/同锅：数据库只放行一张。
            session.rollback()
            return JSONResponse({"detail": "该锅已有现行溶化证，开证冲突，请刷新后重试"}, status_code=409)
        session.refresh(cert)
        return JSONResponse(cert_json(cert), status_code=201)


async def revoke_cert(request: Request):
    user = await current_user(request)
    if user is None:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    # 核销归管理员。
    if user.role != "admin":
        return JSONResponse({"detail": "核销溶化证仅限管理员"}, status_code=403)
    cert_id = int(request.path_params["cert_id"])
    with get_session() as session:
        cert = session.exec(select(MeltCert).where(MeltCert.id == cert_id)).first()
        if cert is None:
            return JSONResponse({"detail": "溶化证不存在"}, status_code=404)
        if cert.revoked_at is not None:
            return JSONResponse({"detail": "该溶化证已核销"}, status_code=400)
        cert.revoked_at = utcnow()
        cert.revoker = user.username
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
        Route("/api/certs", list_certs, methods=["GET"]),
        Route("/api/certs", issue_cert, methods=["POST"]),
        Route("/api/certs/{cert_id:int}/revoke", revoke_cert, methods=["POST"]),
    ],
    middleware=[Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])],
)
