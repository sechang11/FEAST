/* Free FEAST calculator.
 *
 * Talks to the same feastpy code path the desktop app uses; this file only
 * moves text around and draws the result.
 */
"use strict";

const $ = (id) => document.getElementById(id);
let lastResult = null;

function payload() {
  const b = $("bmatrix").value.trim();
  return {
    matrix: $("matrix").value,
    b_matrix: b ? b : null,
    emin: parseFloat($("emin").value),
    emax: parseFloat($("emax").value),
    m0: parseInt($("m0").value, 10) || 40,
    contour_points: parseInt($("cp").value, 10) || 8,
    tol_exponent: parseInt($("tol").value, 10) || 12,
    max_loops: 20,
  };
}

async function post(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({ detail: res.statusText }));
  if (!res.ok) throw new Error(data.detail || `request failed (${res.status})`);
  return data;
}

function setStatus(el, text, isError) {
  el.textContent = text;
  el.classList.toggle("error", !!isError);
}

function needMatrix() {
  if (!$("matrix").value.trim()) throw new Error("Paste a matrix first, or load a sample.");
}

// ---- samples ---------------------------------------------------------------
$("load-sample").addEventListener("click", async () => {
  const name = $("sample").value;
  if (!name) return;
  setStatus($("matinfo"), "loading sample…");
  try {
    const d = await (await fetch(`/api/samples/${name}`)).json();
    $("matrix").value = d.text;
    $("bmatrix").value = d.b_text || "";
    if (d.b_text) $("bwrap").open = true;
    $("emin").value = d.emin;
    $("emax").value = d.emax;
    setStatus($("matinfo"), `${d.name}. ${d.note || ""}`);
  } catch (e) {
    setStatus($("matinfo"), e.message, true);
  }
});

// ---- inspect ---------------------------------------------------------------
$("inspect").addEventListener("click", async () => {
  try {
    needMatrix();
    setStatus($("matinfo"), "reading…");
    const d = await post("/api/bounds", payload());
    setStatus($("matinfo"),
      `${d.sparse ? "sparse" : "dense"} ${d.n}×${d.n}, ` +
      `${d.nnz.toLocaleString()} nonzeros` +
      (d.generalized ? ", generalized" : "") +
      ` — all eigenvalues lie in [${fmt(d.emin)}, ${fmt(d.emax)}]`);
    // Offer the full range: guessing an interval blind is the main way to get
    // an empty result.
    if (!$("emin").dataset.touched) {
      $("emin").value = d.emin;
      $("emax").value = d.emax;
    }
  } catch (e) {
    setStatus($("matinfo"), e.message, true);
  }
});

for (const id of ["emin", "emax"]) {
  $(id).addEventListener("input", () => { $("emin").dataset.touched = "1"; });
}

// ---- estimate --------------------------------------------------------------
$("estimate").addEventListener("click", async () => {
  try {
    needMatrix();
    setStatus($("estinfo"), "estimating…");
    const d = await post("/api/estimate", payload());
    setStatus($("estinfo"),
      `about ${d.count} eigenvalue(s) here (${d.seconds.toFixed(2)}s)`);
    if (d.count > 0) $("m0").value = Math.max(10, Math.round(d.count * 1.5) + 5);
  } catch (e) {
    setStatus($("estinfo"), e.message, true);
  }
});

// ---- solve -----------------------------------------------------------------
$("solve").addEventListener("click", async () => {
  const btn = $("solve");
  try {
    needMatrix();
    btn.disabled = true;
    setStatus($("solveinfo"), "solving…");
    $("diagnosis").hidden = true;
    const d = await post("/api/solve", payload());
    lastResult = d;
    render(d);
  } catch (e) {
    setStatus($("solveinfo"), e.message, true);
    $("results").hidden = true;
  } finally {
    btn.disabled = false;
  }
});

function fmt(x) {
  if (x === 0) return "0";
  return Math.abs(x) < 1e-4 || Math.abs(x) >= 1e6 ? x.toExponential(4) : String(+x.toPrecision(8));
}

function render(d) {
  setStatus($("solveinfo"),
    `${d.n_found} eigenvalue(s), ${d.loops} loop(s), ${d.seconds.toFixed(2)}s`);

  const diag = $("diagnosis");
  if (d.info !== 0 || d.suggestions.length) {
    diag.hidden = false;
    diag.innerHTML =
      `<h3>${escapeHtml(d.headline)}</h3><p>${escapeHtml(d.detail)}</p>` +
      (d.suggestions.length
        ? "<ul>" + d.suggestions.map((s) => `<li>${escapeHtml(s.text)}</li>`).join("") + "</ul>"
        : "");
  } else {
    diag.hidden = true;
  }

  const tbody = document.querySelector("#eigtable tbody");
  tbody.innerHTML = d.eigenvalues
    .map((v, i) => `<tr><td>${i + 1}</td><td>${fmt(v)}</td><td>${d.residuals[i].toExponential(2)}</td></tr>`)
    .join("");
  $("summary").textContent = d.n_found
    ? `found ${d.n_found} in [${fmt(parseFloat($("emin").value))}, ${fmt(parseFloat($("emax").value))}], M0=${d.m0_used}`
    : "nothing found in this interval";
  $("results").hidden = false;
  drawPlot(d.eigenvalues);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* A small inline SVG rather than a charting library: one file, no CDN, and the
   plot is a strip of ticks -- the eigenvalues' positions in the interval. */
function drawPlot(values) {
  const host = $("plot");
  if (!values.length) { host.innerHTML = ""; return; }
  const W = 900, H = 120, pad = 40;
  const lo = Math.min(...values), hi = Math.max(...values);
  const span = hi - lo || Math.abs(hi) || 1;
  const x = (v) => pad + ((v - lo) / span) * (W - 2 * pad);

  const ticks = values.map(
    (v) => `<line x1="${x(v).toFixed(1)}" y1="30" x2="${x(v).toFixed(1)}" y2="72" stroke="var(--band)" stroke-width="2"/>`
  ).join("");

  host.innerHTML = `
<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="eigenvalue positions">
  <line x1="${pad}" y1="72" x2="${W - pad}" y2="72" stroke="currentColor" opacity=".35"/>
  ${ticks}
  <text x="${pad}" y="96" font-size="13" fill="currentColor" opacity=".7">${fmt(lo)}</text>
  <text x="${W - pad}" y="96" font-size="13" fill="currentColor" opacity=".7" text-anchor="end">${fmt(hi)}</text>
  <text x="${W / 2}" y="18" font-size="13" fill="currentColor" opacity=".7" text-anchor="middle">${values.length} eigenvalue(s)</text>
</svg>`;
}

// ---- CSV -------------------------------------------------------------------
$("download-csv").addEventListener("click", () => {
  if (!lastResult) return;
  const rows = ["index,eigenvalue,residual"].concat(
    lastResult.eigenvalues.map((v, i) => `${i + 1},${v},${lastResult.residuals[i]}`));
  const blob = new Blob([rows.join("\n")], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "eigenvalues.csv";
  a.click();
  URL.revokeObjectURL(a.href);
});

// ---- limits ----------------------------------------------------------------
(async () => {
  try {
    const l = await (await fetch("/api/limits")).json();
    $("limits").innerHTML = [
      `Dense matrices up to ${l.max_dense_n}×${l.max_dense_n}`,
      `Sparse matrices up to ${l.max_sparse_n.toLocaleString()} with ${l.max_nnz.toLocaleString()} nonzeros`,
      `Subspace M0 up to ${l.max_m0}`,
      `${l.timeout_s}s per solve, ${l.max_upload_mb} MB per matrix`,
    ].map((t) => `<li>${t}</li>`).join("");
  } catch {
    $("limits").innerHTML = "<li>could not load limits</li>";
  }
})();
