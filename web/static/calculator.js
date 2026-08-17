/* Free FEAST calculator.
 *
 * Talks to the same feastpy code path the desktop app uses; this file only
 * moves text around and draws the result.
 *
 * Two search regions, because FEAST has two. A Hermitian matrix has real
 * eigenvalues, so the region is an interval of the real line. A non-Hermitian
 * one does not, so the region is a disc of the complex plane and the answers
 * come back complex. Nearly everything below that looks like a branch is that
 * one distinction working its way outward.
 */
"use strict";

const $ = (id) => document.getElementById(id);
let lastResult = null;

const mode = () => $("mode").value;
const isDisc = () => mode() === "disc";

function payload() {
  const b = $("bmatrix").value.trim();
  const p = {
    matrix: matrixText(),
    b_matrix: b ? b : null,
    m0: parseInt($("m0").value, 10) || 40,
    contour_points: parseInt($("cp").value, 10) || 8,
    tol_exponent: parseInt($("tol").value, 10) || 12,
    max_loops: 20,
  };
  if (isDisc()) {
    p.center_re = parseFloat($("cre").value) || 0;
    p.center_im = parseFloat($("cim").value) || 0;
    p.radius = parseFloat($("rad").value);
  } else {
    p.emin = parseFloat($("emin").value);
    p.emax = parseFloat($("emax").value);
  }
  return p;
}

async function post(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({ detail: res.statusText }));
  if (!res.ok) throw new Error(detailText(data) || `request failed (${res.status})`);
  return data;
}

/* FastAPI validation errors arrive as a list of objects rather than a string;
   rendering that raw puts "[object Object]" in front of the user. */
function detailText(data) {
  const d = data && data.detail;
  if (!d) return "";
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((e) => e.msg || JSON.stringify(e)).join("; ");
  return String(d);
}

function setStatus(el, text, isError) {
  el.textContent = text;
  el.classList.toggle("error", !!isError);
}

function needMatrix() {
  if (!matrixText()) throw new Error(
    "Load a matrix file first, or paste one, or pick a sample.");
}

// ---- search region ---------------------------------------------------------
function applyMode() {
  $("interval-box").hidden = isDisc();
  $("disc-box").hidden = !isDisc();
  $("results").hidden = true;
  $("diagnosis").hidden = true;
  setStatus($("solveinfo"), "");
}
$("mode").addEventListener("change", applyMode);

/* Inspect knows whether the matrix is Hermitian, so it can pick the mode. When
   it is not, the interval option is disabled outright: an interval search of a
   non-Hermitian matrix is not a worse choice, it is a rejected request, and
   letting someone select it only to be refused wastes the round trip.

   `forcedDisc` remembers that *we* switched to a disc rather than the user, so
   the switch can be undone when the next matrix is Hermitian. Without it the
   mode leaks across matrices: load a non-Hermitian sample, then a Hermitian
   one, and the second is solved with the first one's disc still in the boxes.
   That does not error -- it returns a full set of wrong numbers. */
let forcedDisc = false;

function offerModes(hermitian) {
  const opt = $("mode").querySelector('option[value="interval"]');
  opt.disabled = !hermitian;
  if (!hermitian) {
    forcedDisc = true;
    $("mode").value = "disc";
    setStatus($("modeinfo"),
      "not Hermitian — its eigenvalues are complex, so a disc it is");
  } else {
    if (forcedDisc) $("mode").value = "interval";
    forcedDisc = false;
    setStatus($("modeinfo"), "");
  }
  applyMode();
}

// ---- file upload -----------------------------------------------------------
/* Pasting stops being usable somewhere in the low thousands of nonzeros, and
   the matrices worth solving start above that. The file is parsed on the
   server by the same reader the desktop app uses -- which is what lets .npy,
   .npz and .gz work at all, since none of them are text -- and comes back as
   text the existing endpoints already accept. One solve path, not two.

   The paste box stays. It is better for a small matrix you want to edit. */
let uploaded = null;          // text of the matrix loaded from a file

$("matfile").addEventListener("change", async (ev) => {
  const f = ev.target.files && ev.target.files[0];
  if (!f) return;
  setStatus($("fileinfo"), `reading ${f.name}…`);
  try {
    const body = new FormData();
    body.append("file", f);
    const res = await fetch("/api/upload", { method: "POST", body });
    const d = await res.json().catch(() => ({ detail: res.statusText }));
    if (!res.ok) throw new Error(detailText(d) || `upload failed (${res.status})`);

    uploaded = d.text;
    // Show the matrix only when it is small enough to be worth looking at.
    // Dropping a megabyte of coordinates into a textarea freezes the page,
    // and the user did not ask to read it -- they asked to solve it.
    if (d.text.length <= 200000) {
      $("matrix").value = d.text;
    } else {
      $("matrix").value = "";
      $("matrix").placeholder =
        `${d.name} is loaded (${d.describe}) — too large to display here, ` +
        "but it will be solved.";
    }
    offerModes(d.hermitian);
    if (d.hermitian && d.emin !== undefined) {
      $("emin").value = d.emin;
      $("emax").value = d.emax;
    }
    if (d.disc_is_bound) {
      $("cre").value = round4(d.center_re);
      $("cim").value = round4(d.center_im);
      $("rad").value = round4(d.radius);
    }
    // A loaded matrix comes with a region chosen from its own spectrum, so
    // protect it from Inspect's defaults exactly as a sample's would be.
    $("emin").dataset.touched = "1";
    setStatus($("fileinfo"),
      `${d.name}: ${d.describe}, ${d.hermitian ? "Hermitian" : "non-Hermitian"}`);
    setStatus($("matinfo"), "");
  } catch (e) {
    uploaded = null;
    setStatus($("fileinfo"), e.message, true);
  }
});

/* The textarea is the source of truth when it holds something; `uploaded`
   covers the case where the matrix was too large to display. Reading it back
   from the box would silently solve an empty matrix. */
function matrixText() {
  const typed = $("matrix").value.trim();
  if (typed) return typed;
  if (uploaded) return uploaded;
  return "";
}

// ---- samples ---------------------------------------------------------------
$("load-sample").addEventListener("click", async () => {
  const name = $("sample").value;
  if (!name) return;
  setStatus($("matinfo"), "loading sample…");
  try {
    const d = await (await fetch(`/api/samples/${name}`)).json();
    uploaded = null;
    $("matfile").value = "";
    setStatus($("fileinfo"), "");
    $("matrix").value = d.text;
    $("bmatrix").value = d.b_text || "";
    if (d.b_text) $("bwrap").open = true;
    // A sample states its own mode, so set it outright rather than inferring:
    // the sample knows what it is, and leaving the previous matrix's choice in
    // place is how the wrong region gets used.
    if (d.mode === "disc") {
      offerModes(false);
      $("cre").value = round4(d.center_re);
      $("cim").value = round4(d.center_im);
      $("rad").value = round4(d.radius);
    } else {
      offerModes(true);
      $("mode").value = "interval";
      applyMode();
      $("emin").value = d.emin;
      $("emax").value = d.emax;
    }
    // The sample's region is a chosen one, not a leftover, so protect it from
    // Inspect's defaults exactly as if the user had typed it.
    $("emin").dataset.touched = "1";
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
    offerModes(d.hermitian);

    // Gershgorin bounds A, not the pencil, so "all eigenvalues lie within" is
    // simply false for a generalized problem -- on a random pencil only 4 of
    // 20 were inside. Claim the bound only when the server says it holds.
    let where;
    if (d.hermitian && d.emin !== undefined) {
      where = `all eigenvalues lie in [${fmt(d.emin)}, ${fmt(d.emax)}]`;
    } else if (d.disc_is_bound) {
      where = `all eigenvalues lie within ${fmt(d.radius)} of ${fmtC([d.center_re, d.center_im])}`;
    } else {
      where = "generalized, so there is no cheap bound on where the eigenvalues" +
              " are — A's own Gershgorin disc does not bound the pencil. Choose" +
              " a disc from what you know of the problem.";
    }
    setStatus($("matinfo"),
      `${d.sparse ? "sparse" : "dense"} ${d.n}×${d.n}, ` +
      `${d.nnz.toLocaleString()} nonzeros` +
      (d.complex ? ", complex" : "") +
      (d.generalized ? ", generalized" : "") +
      (d.hermitian ? ", Hermitian" : ", non-Hermitian") +
      ` — ${where}`);

    // Offer the whole spectrum: guessing a region blind is the main way to get
    // an empty result. Two things must not be overwritten, though.
    //
    // A region the user typed, or one a sample supplied -- system3 ships the
    // centre and radius FEAST's own driver uses, and replacing them with a
    // computed guess turned a 16-eigenvalue solve into an empty one.
    //
    // And a generalized problem's disc, which bounds A rather than the pencil.
    // For system3 that is a radius of 5e-18 around zero while the eigenvalues
    // are near 0.6: filling it in would hand the user a region guaranteed to
    // find nothing. Report it, do not adopt it.
    if (!$("emin").dataset.touched) {
      if (d.emin !== undefined) { $("emin").value = d.emin; $("emax").value = d.emax; }
      if (d.disc_is_bound) {
        $("cre").value = round4(d.center_re);
        $("cim").value = round4(d.center_im);
        $("rad").value = round4(d.radius);
      }
    }
  } catch (e) {
    setStatus($("matinfo"), e.message, true);
  }
});

for (const id of ["emin", "emax", "cre", "cim", "rad"]) {
  $(id).addEventListener("input", () => { $("emin").dataset.touched = "1"; });
}

function round4(x) {
  return Number.isFinite(x) ? +x.toPrecision(4) : x;
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

/* A complex number as a person writes it, from the [re, im] pair the API
   sends for a disc search. */
function fmtC(v) {
  const [re, im] = v;
  if (im === 0) return fmt(re);
  const sign = im > 0 ? "+" : "−";
  return `${fmt(re)} ${sign} ${fmt(Math.abs(im))}i`;
}

function render(d) {
  const cx = !!d.complex_eigenvalues;
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

  document.querySelector("#eigtable thead").innerHTML = cx
    ? "<tr><th>#</th><th>real</th><th>imaginary</th><th>residual</th></tr>"
    : "<tr><th>#</th><th>eigenvalue</th><th>residual</th></tr>";

  const tbody = document.querySelector("#eigtable tbody");
  tbody.innerHTML = d.eigenvalues
    .map((v, i) => {
      const r = d.residuals[i].toExponential(2);
      return cx
        ? `<tr><td>${i + 1}</td><td>${fmt(v[0])}</td><td>${fmt(v[1])}</td><td>${r}</td></tr>`
        : `<tr><td>${i + 1}</td><td>${fmt(v)}</td><td>${r}</td></tr>`;
    })
    .join("");

  if (d.n_found) {
    $("summary").textContent = cx
      ? `found ${d.n_found} inside the disc of radius ${fmt(parseFloat($("rad").value))} about ` +
        `${fmtC([parseFloat($("cre").value) || 0, parseFloat($("cim").value) || 0])}, M0=${d.m0_used}`
      : `found ${d.n_found} in [${fmt(parseFloat($("emin").value))}, ${fmt(parseFloat($("emax").value))}], M0=${d.m0_used}`;
  } else {
    $("summary").textContent = cx ? "nothing found in this disc" : "nothing found in this interval";
  }

  $("results").hidden = false;
  if (cx) {
    drawArgand(d.eigenvalues,
      parseFloat($("cre").value) || 0,
      parseFloat($("cim").value) || 0,
      parseFloat($("rad").value));
  } else {
    drawPlot(d.eigenvalues);
  }
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

/* The complex plane, with the contour drawn on it.
 *
 * This is the picture the interval plot cannot show: the eigenvalues sitting
 * off the real axis, and the circle FEAST integrated around to find exactly
 * the ones inside it. Equal scale on both axes -- an anisotropic plot would
 * draw the contour as an ellipse, which is a different algorithm.
 */
function drawArgand(values, cre, cim, rad) {
  const host = $("plot");
  if (!values.length && !Number.isFinite(rad)) { host.innerHTML = ""; return; }
  const W = 640, H = 460, pad = 46;

  // Frame everything: the contour and any eigenvalue, including ones outside
  // it -- FEAST can return a slot just beyond the circle, and silently
  // cropping it would hide the most interesting thing on the plot.
  let lo = cre - rad, hi = cre + rad, blo = cim - rad, bhi = cim + rad;
  for (const [re, im] of values) {
    lo = Math.min(lo, re); hi = Math.max(hi, re);
    blo = Math.min(blo, im); bhi = Math.max(bhi, im);
  }
  const cx = (lo + hi) / 2, cy = (blo + bhi) / 2;
  const half = Math.max(hi - lo, bhi - blo, 1e-12) / 2 * 1.12;

  const sc = (W - 2 * pad) / (2 * half);            // one scale, both axes
  const X = (v) => pad + (v - (cx - half)) * sc;
  const Y = (v) => H / 2 - (v - cy) * sc;           // imaginary axis points up

  const dots = values.map(([re, im]) =>
    `<circle cx="${X(re).toFixed(1)}" cy="${Y(im).toFixed(1)}" r="3.2" fill="var(--band)"/>`
  ).join("");

  const axisY = Y(0), axisX = X(0);
  const inFrame = (v, a, b) => v >= a && v <= b;

  host.innerHTML = `
<svg viewBox="0 0 ${W} ${H}" role="img"
     aria-label="${values.length} eigenvalues in the complex plane, with the search contour">
  ${inFrame(axisY, 0, H) ? `<line x1="${pad}" y1="${axisY.toFixed(1)}" x2="${W - pad}" y2="${axisY.toFixed(1)}" stroke="currentColor" opacity=".28"/>` : ""}
  ${inFrame(axisX, 0, W) ? `<line x1="${axisX.toFixed(1)}" y1="${pad * 0.4}" x2="${axisX.toFixed(1)}" y2="${H - pad * 0.6}" stroke="currentColor" opacity=".28"/>` : ""}
  <circle cx="${X(cre).toFixed(1)}" cy="${Y(cim).toFixed(1)}" r="${(rad * sc).toFixed(1)}"
          fill="var(--band)" fill-opacity=".08"
          stroke="var(--band)" stroke-opacity=".85" stroke-width="1.6" stroke-dasharray="5 4"/>
  <circle cx="${X(cre).toFixed(1)}" cy="${Y(cim).toFixed(1)}" r="2.5"
          fill="none" stroke="currentColor" opacity=".5"/>
  ${dots}
  <text x="${W - pad}" y="${H - 12}" font-size="12" fill="currentColor" opacity=".7" text-anchor="end">real →</text>
  <text x="${pad - 34}" y="${pad * 0.4 + 4}" font-size="12" fill="currentColor" opacity=".7">imag ↑</text>
  <text x="${W / 2}" y="18" font-size="13" fill="currentColor" opacity=".75" text-anchor="middle">
    ${values.length} eigenvalue(s) inside the contour
  </text>
</svg>`;
}

// ---- CSV -------------------------------------------------------------------
$("download-csv").addEventListener("click", () => {
  if (!lastResult) return;
  const cx = !!lastResult.complex_eigenvalues;
  const head = cx ? "index,real,imaginary,residual" : "index,eigenvalue,residual";
  const rows = [head].concat(
    lastResult.eigenvalues.map((v, i) =>
      cx ? `${i + 1},${v[0]},${v[1]},${lastResult.residuals[i]}`
         : `${i + 1},${v},${lastResult.residuals[i]}`));
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
