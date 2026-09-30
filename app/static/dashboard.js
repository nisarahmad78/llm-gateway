// LLM Gateway dashboard — polls the gateway's own JSON endpoints.
const REFRESH_MS = 5000;

const $ = (id) => document.getElementById(id);

function fmtNumber(n) {
  return Number(n || 0).toLocaleString("en-US");
}

function fmtCost(n) {
  const value = Number(n || 0);
  return "$" + value.toFixed(value < 0.01 ? 4 : 2);
}

function fmtLatency(ms) {
  const value = Number(ms || 0);
  return value >= 1000 ? (value / 1000).toFixed(2) + " s" : Math.round(value) + " ms";
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = String(text ?? "");
  return div.innerHTML;
}

function renderBars(containerId, rows, nameKey, alt) {
  const container = $(containerId);
  if (!rows || rows.length === 0) return;
  const max = Math.max(...rows.map((r) => r.requests), 1);
  container.innerHTML = rows
    .map((r) => {
      const pct = Math.round((r.requests / max) * 100);
      return `
        <div class="bar-row">
          <div class="bar-label">
            <span>${escapeHtml(r[nameKey])}</span>
            <span>${fmtNumber(r.requests)} req · ${fmtNumber(r.tokens)} tok · ${fmtCost(r.cost)}</span>
          </div>
          <div class="bar-track"><div class="bar-fill${alt ? " alt" : ""}" style="width:${pct}%"></div></div>
        </div>`;
    })
    .join("");
}

function statusBadge(row) {
  if (row.status === "ok") return '<span class="badge badge-ok">ok</span>';
  if (row.status === "rate_limited") return '<span class="badge badge-rate">rate limited</span>';
  return `<span class="badge badge-error">${escapeHtml(row.status)}</span>`;
}

function renderRequests(rows) {
  const body = $("requests-body");
  if (!rows || rows.length === 0) return;
  body.innerHTML = rows
    .map(
      (r) => `
      <tr>
        <td>${escapeHtml(r.ts)}</td>
        <td>${escapeHtml(r.api_key)}</td>
        <td>${escapeHtml(r.model)}${r.stream ? " · stream" : ""}</td>
        <td>${escapeHtml(r.provider)}</td>
        <td>${fmtNumber(r.prompt_tokens)} / ${fmtNumber(r.completion_tokens)}</td>
        <td>${fmtLatency(r.latency_ms)}</td>
        <td>${fmtCost(r.estimated_cost)}</td>
        <td>${statusBadge(r)}</td>
      </tr>`
    )
    .join("");
}

async function refresh() {
  try {
    const [statsRes, reqRes, healthRes] = await Promise.all([
      fetch("/api/stats"),
      fetch("/api/requests?limit=25"),
      fetch("/health"),
    ]);
    const stats = await statsRes.json();
    const requests = await reqRes.json();
    const health = await healthRes.json();

    const t = stats.totals || {};
    $("stat-requests").textContent = fmtNumber(t.total_requests);
    $("stat-ok").textContent = fmtNumber(t.ok_count);
    $("stat-errors").textContent = fmtNumber(t.error_count);
    $("stat-tokens").textContent = fmtNumber(
      Number(t.prompt_tokens || 0) + Number(t.completion_tokens || 0)
    );
    $("stat-prompt-tokens").textContent = fmtNumber(t.prompt_tokens);
    $("stat-completion-tokens").textContent = fmtNumber(t.completion_tokens);
    $("stat-cost").textContent = fmtCost(t.total_cost);
    $("stat-latency").textContent = fmtLatency(t.avg_latency_ms);

    renderBars("by-model", stats.by_model, "model", false);
    renderBars("by-provider", stats.by_provider, "provider", true);
    renderRequests(requests.data);

    const pill = $("health-pill");
    pill.textContent = health.status === "ok" ? "gateway healthy" : "gateway " + health.status;
    pill.className = "pill " + (health.status === "ok" ? "pill-ok" : "pill-bad");

    $("updated-at").textContent = new Date().toLocaleTimeString();
  } catch (err) {
    const pill = $("health-pill");
    pill.textContent = "gateway unreachable";
    pill.className = "pill pill-bad";
  }
}

refresh();
setInterval(refresh, REFRESH_MS);
