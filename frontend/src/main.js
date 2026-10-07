import "./style.css";

const TOKEN_KEY = "gluekettle_token";
const LABELS = { cold: "冷锅", boiling: "熬煮中", drawn: "已出胶" };

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  const t = localStorage.getItem(TOKEN_KEY);
  if (t) headers.Authorization = `Bearer ${t}`;
  const res = await fetch(path, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(data.detail || "请求失败"), { status: res.status });
  return data;
}

const app = document.getElementById("app");
const state = {
  ready: Boolean(localStorage.getItem(TOKEN_KEY)),
  board: null,
  view: "board",
  me: null,
  picked: null,
  peak: "96",
  certKettleId: null,
  certs: [],
  certNo: "1",
  meltTemp: "80",
  err: "",
  username: "admin",
  password: "123456",
};

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString("zh-CN", { hour12: false });
}

async function refreshBoard() {
  state.board = await api("/api/board");
  if (state.picked) {
    state.picked = state.board.kettles.find((k) => k.id === state.picked.id) || state.board.kettles[0];
  }
}

async function refreshCerts() {
  if (!state.certKettleId) return;
  const data = await api(`/api/kettles/${state.certKettleId}/melt-certs`);
  state.certs = data.certs;
}

async function refresh() {
  if (state.view === "certs") {
    await refreshBoard();
    await refreshCerts();
  } else {
    await refreshBoard();
  }
  render();
}

function nav(box) {
  const bar = box.querySelector(".nav");
  bar.querySelector("[data-v=board]").onclick = () => {
    state.view = "board";
    state.err = "";
    render();
  };
  bar.querySelector("[data-v=certs]").onclick = () => {
    state.view = "certs";
    state.err = "";
    if (!state.certKettleId && state.board) state.certKettleId = state.board.kettles[0]?.id ?? null;
    refreshCerts().then(render).catch((e) => {
      state.err = e.message;
      render();
    });
  };
  bar.querySelector("#logout").onclick = () => {
    localStorage.removeItem(TOKEN_KEY);
    location.reload();
  };
}

function renderLogin() {
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
      state.me = data.user;
      state.ready = true;
      await refreshBoard();
      render();
    } catch (ex) {
      state.err = ex.message;
      render();
    }
  };
  app.append(box);
}

function renderBoard(box) {
  const page = box.querySelector(".page-board");
  const row = page.querySelector(".row");
  state.board.kettles.forEach((k) => {
    const badge = k.activeCertNo != null ? `<em class="cert-badge">证 ${esc(k.activeCertNo)}</em>` : `<em class="cert-badge none">无证</em>`;
    const btn = el(`<button class="kettle ${k.status}"><strong>${esc(k.code)}</strong><span>${LABELS[k.status]}</span>${badge}</button>`);
    btn.onclick = () => {
      state.picked = k;
      render();
    };
    row.append(btn);
  });
  if (state.picked) {
    const d = page.querySelector(".drawer");
    const certLine =
      state.picked.activeCertNo != null
        ? `未核销溶化证：第 ${esc(state.picked.activeCertNo)} 号（有证方可登记峰值）`
        : `无未核销溶化证：登记峰值将被拒绝，请到「溶化证」开证`;
    d.innerHTML = `<h3>${esc(state.picked.code)} · ${LABELS[state.picked.status]}</h3>
      <p>最近峰值：${esc(state.picked.latestPeakC ?? "无")} ℃ · ${esc(state.picked.cookCount)} 次</p>
      <p class="hint">${certLine}</p>
      <input id="peak" value="${esc(state.peak)}" />
      <button id="log">登记峰值</button>
      <div>
        <button data-s="cold">冷锅</button>
        <button data-s="boiling">熬煮中</button>
        <button data-s="drawn">已出胶</button>
      </div>`;
    d.querySelector("#log").onclick = async () => {
      state.err = "";
      state.peak = d.querySelector("#peak").value;
      try {
        state.picked = await api(`/api/kettles/${state.picked.id}/cooks`, {
          method: "POST",
          body: JSON.stringify({ peakTempC: Number(state.peak) }),
        });
        await refreshBoard();
        render();
      } catch (ex) {
        state.err = ex.message;
        render();
      }
    };
    d.querySelectorAll("[data-s]").forEach((b) => {
      b.onclick = async () => {
        state.err = "";
        try {
          state.picked = await api(`/api/kettles/${state.picked.id}/status`, {
            method: "POST",
            body: JSON.stringify({ status: b.dataset.s }),
          });
          await refreshBoard();
          render();
        } catch (ex) {
          state.err = ex.message;
          render();
        }
      };
    });
  }
}

function certRowsHtml() {
  if (!state.certs.length) return `<tr><td colspan="6" class="hint">该锅暂无溶化证</td></tr>`;
  const isAdmin = state.me?.role === "admin";
  return state.certs
    .map((c) => {
      const active = c.usedAt == null;
      const action = active
        ? isAdmin
          ? `<button data-redeem="${c.id}">核销</button>`
          : `<span class="hint">待管理员核销</span>`
        : `<span class="done">已于 ${esc(fmtTime(c.usedAt))} 由 ${esc(c.usedBy)} 核销</span>`;
      return `<tr class="${active ? "active-row" : ""}">
        <td>${esc(c.certNo)}</td>
        <td>${esc(c.meltTempC)} ℃</td>
        <td>${esc(c.issuedBy)}</td>
        <td>${esc(fmtTime(c.issuedAt))}</td>
        <td>${active ? `<strong>现行</strong>` : "已核销"}</td>
        <td>${action}</td>
      </tr>`;
    })
    .join("");
}

function renderCerts(box) {
  const page = box.querySelector(".page-certs");
  const sel = page.querySelector("#kettlePick");
  sel.innerHTML = state.board.kettles
    .map(
      (k) =>
        `<option value="${k.id}" ${k.id === state.certKettleId ? "selected" : ""}>${esc(k.code)} · ${
          LABELS[k.status]
        }${k.activeCertNo != null ? ` · 现行证 ${k.activeCertNo}` : " · 无证"}</option>`
    )
    .join("");
  sel.onchange = async () => {
    state.certKettleId = Number(sel.value);
    state.err = "";
    await refreshCerts();
    render();
  };
  page.querySelector("#certNo").value = state.certNo;
  page.querySelector("#meltTemp").value = state.meltTemp;
  page.querySelector("tbody").innerHTML = certRowsHtml();

  page.querySelector("#issueForm").onsubmit = async (e) => {
    e.preventDefault();
    state.err = "";
    state.certNo = page.querySelector("#certNo").value;
    state.meltTemp = page.querySelector("#meltTemp").value;
    if (!state.certKettleId) return;
    try {
      await api(`/api/kettles/${state.certKettleId}/melt-certs`, {
        method: "POST",
        body: JSON.stringify({ certNo: Number(state.certNo), meltTempC: Number(state.meltTemp) }),
      });
      await refreshBoard();
      await refreshCerts();
      render();
    } catch (ex) {
      state.err = ex.message;
      render();
    }
  };

  page.querySelectorAll("[data-redeem]").forEach((b) => {
    b.onclick = async () => {
      state.err = "";
      try {
        await api(`/api/melt-certs/${b.dataset.redeem}/redeem`, { method: "POST" });
        await refreshBoard();
        await refreshCerts();
        render();
      } catch (ex) {
        state.err = ex.message;
        render();
      }
    };
  });
}

function render() {
  app.innerHTML = "";
  if (!state.ready) {
    renderLogin();
    return;
  }
  if (!state.board) {
    app.append(el(`<div class="wrap">${esc(state.err) || "装载锅位…"}</div>`));
    return;
  }
  const box = el(`<div class="wrap">
    <nav class="nav">
      <span class="brand">骨巷熬胶坊</span>
      <button data-v="board" class="${state.view === "board" ? "on" : ""}">锅位作业台</button>
      <button data-v="certs" class="${state.view === "certs" ? "on" : ""}">溶化证</button>
      <span class="spacer"></span>
      <span class="hint">${esc(state.me?.username || "")} · ${state.me?.role === "admin" ? "管理员" : "操作工"}</span>
      <button id="logout">退出</button>
    </nav>
    <p class="err">${esc(state.err)}</p>
    <section class="page-board" ${state.view === "board" ? "" : "hidden"}>
      <p>${esc(state.board.alley)} · 点锅登记峰值；出胶须最近峰值 ≥ 90℃，且登记峰值须先有未核销溶化证</p>
      <div class="row"></div>
      <section class="drawer"></section>
    </section>
    <section class="page-certs" ${state.view === "certs" ? "" : "hidden"}>
      <h2>溶化证</h2>
      <div class="panel">
        <h3>按锅筛列表</h3>
        <label>锅位 <select id="kettlePick"></select></label>
        <table>
          <thead><tr><th>证号</th><th>溶化温度</th><th>开证人</th><th>开证时刻</th><th>状态</th><th>核销</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
      <div class="panel">
        <h3>开证 / 核销</h3>
        <form id="issueForm">
          <label>证号（从 1 起，本锅现行证号不得重复） <input id="certNo" inputmode="numeric" /></label>
          <label>溶化温度（正数且 ≥ 70℃） <input id="meltTemp" inputmode="decimal" /></label>
          <button>开证（操作工可开）</button>
        </form>
        <p class="hint">核销归管理员：在上区列表点「核销」。核销后同号可再开。</p>
      </div>
    </section>
  </div>`);
  nav(box);
  renderBoard(box);
  renderCerts(box);
  app.append(box);
}

async function boot() {
  if (state.ready) {
    try {
      state.me = await api("/api/auth/me");
    } catch {
      state.ready = false;
    }
  }
  if (state.ready) {
    try {
      await refreshBoard();
    } catch (e) {
      state.err = e.message;
    }
  }
  render();
}

boot();
