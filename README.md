# GlueKettle-01 · 骨巷熬胶坊

一排熬锅作业台。登录后是横向锅位，点锅登记煮胶峰值并改状态。前端是原生 JS，没有 React/Vue/Svelte。

## 技术栈

| 层 | 技术 |
| --- | --- |
| Web API | Starlette 路由表（不是 FastAPI Depends） |
| 结构 | SQLModel 实体 + `domain.py` 门槛 |
| 数据 | SQLModel / SQLAlchemy · psycopg2 · PostgreSQL 15 |
| 前端 | 原生 ES Module · Vite 仅打包 |
| 部署 | Docker Compose |

## 路径与端口

- 前端：http://localhost:4790
- API：http://localhost:8790
- PostgreSQL：localhost:6190

## 演示账号

`admin` / `123456`，`worker` / `123456`

## 业务规则

- 锅不可标「已出胶」，除非最近一次煮胶峰值 **≥ 90℃**。规则在 `backend/app/domain.py`。
- **溶化证**：证号从 1 起，记录溶化温度（须为正数且 **≥ 70℃**）、开证人、开证时刻，核销时刻可空。本锅现行（未核销）证号唯一，数据库部分唯一索引兜底并发，核销后同号可再开；跨锅可同号。
- 操作工可开证；**核销归管理员**。
- **登记峰值前必须存在本锅未核销溶化证**，否则整笔拒绝（峰值不入库）。改锅态不看溶化证；已出胶仍只认峰值门槛。
- 顶栏可进入「锅位作业台」与「溶化证」独立专页（上区按锅筛列表，下区开证/核销）。

## 快速启动

```bash
cd GlueKettle/GlueKettle-01
docker compose up --build
```
