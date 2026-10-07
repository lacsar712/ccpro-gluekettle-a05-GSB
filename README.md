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

规则集中在 `backend/app/domain.py`：

- **溶化证**：一口锅至多一张现行（未核销）证；证号在本锅从 1 起顺序发放；溶化温度须为正数且 **≥ 70℃**。操作工可开证，核销归管理员。
- **登记峰值**：该锅必须存在未核销溶化证，否则整笔拒绝、峰值不得先入库。
- **改锅态**：不看溶化证。
- **出胶门槛**：只认最近一次煮胶峰值 **≥ 90℃**。
- 并发抢开同一锅/同一证号由数据库局部唯一索引兜底（`revoked_at IS NULL` 唯一），冲突返回 409，库里只留一张。

页面：顶栏可进入「锅位作业台」与「溶化证」；溶化证为独立专页，上区按锅筛选台账，下区开证与核销。

## 快速启动

```bash
cd GlueKettle/GlueKettle-01
docker compose up --build
```
