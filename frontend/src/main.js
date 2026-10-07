import "./style.css";

const TOKEN_KEY = "gluekettle_token";
const LABELS = { cold: "冷锅", boiling: "熬煮中", drawn: "已出胶" };
const ROLE_LABELS = { admin: "管理员", worker: "操作工" };

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  const t = localStorage.getItem(TOKEN_KEY);
  if (t) headers.Authorization = `Bearer ${t}`;
  const res = await fetch(path, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "请求失败");
  return data;
}

const app = document.getElementById("app");
const state = {
  ready: false,
  user: null,
  page: "board",
  board: null,
  pickedId: null,
  peak: "96",
  certs: [],
  certKettleFilter: "all",
  issueKettleId: "",
  issueTemp: "72",
  revokeKettleId: "",
  err: "",
  msg: "",
  username: "admin",
  password: "123456",
};

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("zh-CN", { hour12: false });
}

async function loadBoard() {
  state.board = await api("/api/board");
  if (state.pickedId == null && state.board.kettles.length) state.pickedId = state.board.kettles[0].id;
}

async function loadCerts() {
  const q = state.certKettleFilter === "all" ? "" : `?kettle_id=${state.certKettleFilter}`;
  state.certs = (await api(`/api/certs${q}`)).certs;
}

async function refreshAll() {
  await Promise.all([loadBoard(), loadCerts()]);
  render();
}

function logout() {
  localStorage.removeItem(TOKEN_KEY);
  location.reload();
}

function topbar() {
  return el(`<header class="topbar">
    <span class="brand">骨巷熬胶坊</span>
    <nav>
      <button data-page="board" class="nav ${state.page === "board" ? "on" : ""}">锅位作业台</button>
      <button data-page="certs" class="nav ${state.page === "certs" ? "on" : ""}">溶化证</button>
    </nav>
    <span class="who">${esc(state.user.username)} · ${ROLE_LABELS[state.user.role] || state.user.role}
      <button id="logout" class="link">退出</button>
    </span>
  </header>`);
}

function boardPage() {
  const picked = state.board.kettles.find((k) => k.id === state.pickedId) || null;
  const box = el(`<div class="wrap">
    <p>${esc(state.board.alley)} · 点锅登记峰值；登记前须持有未核销溶化证；出胶须最近峰值 ≥ 90℃</p>
    <div class="row"></div>
    <section class="drawer"></section>
    <p class="err">${esc(state.err)}</p><p class="msg">${esc(state.msg)}</p>
  </div>`);
  const row = box.querySelector(".row");
  state.board.kettles.forEach((k) => {
    const has = k.activeCert ? " has-cert" : "";
    const btn = el(`<button class="kettle ${k.status}${k.id === state.pickedId ? " picked" : ""}${has}">
      <strong>${esc(k.code)}</strong><span>${LABELS[k.status]}</span>
      <small>${k.activeCert ? `证 #${k.activeCert.certNo}` : "无证"}</small>
    </button>`);
    btn.onclick = () => {
      state.pickedId = k.id;
      state.err = "";
      state.msg = "";
      render();
    };
    row.append(btn);
  });
  const d = box.querySelector(".drawer");
  if (picked) {
    const cert = picked.activeCert;
    d.innerHTML = `<h3>${esc(picked.code)} · ${LABELS[picked.status]}</h3>
      <p>最近峰值：${picked.latestPeakC ?? "无"} ℃ · 煮胶 ${picked.cookCount} 次</p>
      <div class="certline ${cert ? "ok" : "no"}">
        ${
          cert
            ? `现行溶化证：<b>#${cert.certNo}</b> · 溶化 ${cert.meltTempC}℃ · 开证人 ${esc(cert.issuer)} · ${esc(fmtTime(cert.issuedAt))}`
            : `无未核销溶化证——不能登记峰值，先到「溶化证」页开证`
        }
      </div>
      <input id="peak" value="${esc(state.peak)}" ${cert ? "" : "disabled"} placeholder="峰值温度 ℃" />
      <button id="log" ${cert ? "" : "disabled"}>登记峰值</button>
      <div class="statusbtns">
        <button data-s="cold">冷锅</button>
        <button data-s="boiling">熬煮中</button>
        <button data-s="drawn">已出胶</button>
      </div>`;
    d.querySelector("#log").onclick = async () => {
      state.err = "";
      state.msg = "";
      state.peak = d.querySelector("#peak").value;
      try {
        await api(`/api/kettles/${picked.id}/cooks`, {
          method: "POST",
          body: JSON.stringify({ peakTempC: Number(state.peak) }),
        });
        await loadBoard();
        render();
      } catch (ex) {
        state.err = ex.message;
        render();
      }
    };
    d.querySelectorAll("[data-s]").forEach((b) => {
      b.onclick = async () => {
        state.err = "";
        state.msg = "";
        try {
          await api(`/api/kettles/${picked.id}/status`, {
            method: "POST",
            body: JSON.stringify({ status: b.dataset.s }),
          });
          await loadBoard();
          render();
        } catch (ex) {
          state.err = ex.message;
          render();
        }
      };
    });
  }
  return box;
}

function certsPage() {
  const isAdmin = state.user.role === "admin";
  const box = el(`<div class="wrap">
    <section class="panel">
      <h2>溶化证台账</h2>
      <label class="filter">按锅筛选
        <select id="filter">
          <option value="all" ${state.certKettleFilter === "all" ? "selected" : ""}>全部锅</option>
          ${state.board.kettles
            .map(
              (k) =>
                `<option value="${k.id}" ${String(state.certKettleFilter) === String(k.id) ? "selected" : ""}>${esc(k.code)}</option>`
            )
            .join("")}
        </select>
      </label>
      <table class="certtable">
        <thead><tr><th>锅</th><th>证号</th><th>溶化温度</th><th>开证人</th><th>开证时刻</th><th>状态</th><th>核销</th><th></th></tr></thead>
        <tbody></tbody>
      </table>
    </section>
    <section class="panel two">
      <div class="card">
        <h3>开证（操作工）</h3>
        <label>锅位
          <select id="issueKettle">
            <option value="">请选锅</option>
            ${state.board.kettles
              .map(
                (k) =>
                  `<option value="${k.id}" ${String(state.issueKettleId) === String(k.id) ? "selected" : ""}>${esc(k.code)}${k.activeCert ? "（已有现行证）" : ""}</option>`
              )
              .join("")}
          </select>
        </label>
        <label>溶化温度（正数，≥ 70℃）
          <input id="issueTemp" value="${esc(state.issueTemp)}" />
        </label>
        <button id="issue">开证</button>
      </div>
      <div class="card">
        <h3>核销（管理员）</h3>
        <label>锅位
          <select id="revokeKettle" ${isAdmin ? "" : "disabled"}>
            <option value="">请选锅</option>
            ${state.board.kettles
              .map(
                (k) =>
                  `<option value="${k.id}" ${String(state.revokeKettleId) === String(k.id) ? "selected" : ""}>${esc(k.code)}</option>`
              )
              .join("")}
          </select>
        </label>
        <div id="revokeBox" class="revokebox"></div>
      </div>
    </section>
    <p class="err">${esc(state.err)}</p><p class="msg">${esc(state.msg)}</p>
  </div>`);

  const tbody = box.querySelector("tbody");
  if (!state.certs.length) {
    tbody.append(el(`<tr><td colspan="8" class="empty">暂无溶化证</td></tr>`));
  }
  state.certs.forEach((c) => {
    const active = !c.revokedAt;
    const tr = el(`<tr>
      <td>${esc(c.kettleCode)}</td>
      <td>#${c.certNo}</td>
      <td>${c.meltTempC}℃</td>
      <td>${esc(c.issuer)}</td>
      <td>${esc(fmtTime(c.issuedAt))}</td>
      <td><span class="badge ${active ? "live" : "done"}">${active ? "现行" : "已核销"}</span></td>
      <td>${active ? "—" : `${esc(fmtTime(c.revokedAt))} · ${esc(c.revoker || "")}`}</td>
      <td></td>
    </tr>`);
    if (active && isAdmin) {
      const b = el(`<button class="small">核销</button>`);
      b.onclick = () => doRevoke(c.id);
      tr.lastElementChild.append(b);
    }
    tbody.append(tr);
  });

  box.querySelector("#filter").onchange = async (e) => {
    state.certKettleFilter = e.target.value;
    state.err = "";
    state.msg = "";
    await loadCerts();
    render();
  };

  const issueKettle = box.querySelector("#issueKettle");
  issueKettle.onchange = () => {
    state.issueKettleId = issueKettle.value;
  };
  box.querySelector("#issueTemp").oninput = (e) => {
    state.issueTemp = e.target.value;
  };
  box.querySelector("#issue").onclick = async () => {
    state.err = "";
    state.msg = "";
    if (!state.issueKettleId) {
      state.err = "请先选择锅位";
      render();
      return;
    }
    try {
      const c = await api("/api/certs", {
        method: "POST",
        body: JSON.stringify({ kettleId: Number(state.issueKettleId), meltTempC: Number(state.issueTemp) }),
      });
      state.msg = `已为该锅开证 #${c.certNo}（${c.meltTempC}℃）`;
      state.revokeKettleId = state.issueKettleId;
      await refreshAll();
    } catch (ex) {
      state.err = ex.message;
      render();
    }
  };

  const revokeKettle = box.querySelector("#revokeKettle");
  const renderRevokeBox = () => {
    const rb = box.querySelector("#revokeBox");
    rb.innerHTML = "";
    if (!isAdmin) {
      rb.append(el(`<p class="hint">核销归管理员，当前为${ROLE_LABELS[state.user.role] || state.user.role}账号。</p>`));
      return;
    }
    const k = state.board.kettles.find((x) => String(x.id) === String(state.revokeKettleId));
    if (!k) {
      rb.append(el(`<p class="hint">选锅后核销其现行证。</p>`));
      return;
    }
    if (!k.activeCert) {
      rb.append(el(`<p class="hint">${esc(k.code)} 没有未核销溶化证。</p>`));
      return;
    }
    const c = k.activeCert;
    const row = el(`<div class="certline ok">现行证 <b>#${c.certNo}</b> · ${c.meltTempC}℃ · ${esc(c.issuer)} · ${esc(fmtTime(c.issuedAt))}
      <button class="small" data-id="${c.id}">核销该证</button></div>`);
    row.querySelector("button").onclick = () => doRevoke(c.id);
    rb.append(row);
  };
  revokeKettle.onchange = () => {
    state.revokeKettleId = revokeKettle.value;
    renderRevokeBox();
  };
  renderRevokeBox();

  async function doRevoke(certId) {
    state.err = "";
    state.msg = "";
    try {
      await api(`/api/certs/${certId}/revoke`, { method: "POST", body: "{}" });
      state.msg = "溶化证已核销";
      await refreshAll();
    } catch (ex) {
      state.err = ex.message;
      render();
    }
  }

  return box;
}

function render() {
  app.innerHTML = "";
  if (!state.ready) {
    const box = el(`<div class="wrap">
      <h1>骨巷熬胶坊</h1>
      <p>一排熬锅作业台，原生页面，无前端框架。</p>
      <form autocomplete="off">
        <label>用户名
          <input name="u" autocomplete="off" value="${esc(state.username)}" />
        </label>
        <label>密码
          <input name="p" type="password" autocomplete="off" value="${esc(state.password)}" />
        </label>
        <p class="hint">已预填 admin / 123456，另有 worker / 123456</p>
        <button>登录</button>
      </form>
      <p class="err">${esc(state.err)}</p>
    </div>`);
    box.querySelector("form").onsubmit = async (e) => {
      e.preventDefault();
      state.err = "";
      try {
        const data = await api("/api/auth/login", {
          method: "POST",
          body: JSON.stringify({
            username: box.querySelector("[name=u]").value,
            password: box.querySelector("[name=p]").value,
          }),
        });
        localStorage.setItem(TOKEN_KEY, data.access_token);
        state.user = data.user;
        state.ready = true;
        await refreshAll();
      } catch (ex) {
        state.err = ex.message;
        render();
      }
    };
    app.append(box);
    return;
  }
  if (!state.board) {
    app.append(el(`<div class="wrap">${state.err ? `<p class="err">${esc(state.err)}</p>` : "装载锅位…"}</div>`));
    return;
  }
  const shell = el(`<div><header class="topbar-slot"></header><main class="page-slot"></main></div>`);
  const bar = topbar();
  bar.querySelectorAll(".nav").forEach((b) => {
    b.onclick = () => {
      state.page = b.dataset.page;
      state.err = "";
      state.msg = "";
      render();
    };
  });
  bar.querySelector("#logout").onclick = logout;
  shell.querySelector(".topbar-slot").replaceWith(bar);
  shell.querySelector(".page-slot").append(state.page === "certs" ? certsPage() : boardPage());
  app.append(shell);
}

async function boot() {
  if (!localStorage.getItem(TOKEN_KEY)) {
    render();
    return;
  }
  try {
    state.user = await api("/api/auth/me");
    state.ready = true;
    await refreshAll();
  } catch {
    localStorage.removeItem(TOKEN_KEY);
    render();
  }
}

boot();
