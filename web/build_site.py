"""Generate the static site into web/static/.

One template, one nav, one stylesheet -- pages are content only.

    python build_site.py

The copy here is written for this distribution. It deliberately does not
reproduce text from feast-solver.org; it describes what this build adds (the
desktop app and the web calculator) and credits the solver's authors.
"""
from __future__ import annotations

import html
from pathlib import Path

from compat_page import COMPATIBILITY  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "static"

NAV = [
    ("index.html", "Home"),
    ("features.html", "Features"),
    ("calculator.html", "Calculator"),
    ("documentation.html", "Documentation"),
    ("download.html", "Download"),
    ("compatibility.html", "Compatibility"),
    ("license.html", "License"),
    ("references.html", "References"),
    ("contact.html", "Contact"),
]

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} &mdash; FEAST Eigenvalue Solver</title>
<meta name="description" content="{description}">
<link rel="stylesheet" href="style.css">
{head_extra}
</head>
<body>
<header class="banner">
  <div class="wrap">
    <a class="brand" href="index.html">
      <span class="mark" aria-hidden="true">&Lambda;</span>
      <span>
        <strong>FEAST</strong>
        <em>Eigenvalue Solver</em>
      </span>
    </a>
    <p class="tagline">Contour-integration eigensolver &mdash; v4.0, with a
      cross-platform desktop app and a free online calculator</p>
  </div>
</header>

<nav class="mainnav"><div class="wrap">{nav}</div></nav>

<main class="wrap">
{body}
</main>

<footer class="wrap">
  <p>FEAST is copyright &copy; 2009&ndash;2020 The Regents of the University of
     Massachusetts, Amherst (E. Polizzi research lab), distributed under the BSD
     licence. See <a href="license.html">License</a>.</p>
  <p>This distribution adds the desktop application, the Python interface and
     this site. The solver itself is unmodified.</p>
</footer>
{body_extra}
</body>
</html>
"""


def render(active: str, title: str, description: str, body: str,
           head_extra: str = "", body_extra: str = "") -> str:
    nav = "".join(
        '<a href="{}"{}>{}</a>'.format(
            href, ' class="active"' if href == active else "", label)
        for href, label in NAV)
    return TEMPLATE.format(title=html.escape(title), description=html.escape(description),
                           nav=nav, body=body, head_extra=head_extra,
                           body_extra=body_extra)


# ---------------------------------------------------------------- pages -----

HOME = """
<section class="hero">
  <h1>Every eigenvalue in an interval &mdash; not the first <em>k</em></h1>
  <p class="lead">FEAST solves standard, generalized and polynomial eigenvalue
     problems by contour integration. You give it a region &mdash; an interval
     on the real line, or a disc in the complex plane &mdash; and it returns
     everything inside, with a residual for each.</p>
  <p class="cta">
    <a class="button primary" href="calculator.html">Try the free calculator</a>
    <a class="button" href="download.html">Download the desktop app</a>
  </p>
</section>

<section class="cols">
  <div>
    <h2>What this distribution adds</h2>
    <ul>
      <li><strong>A desktop application</strong> for Windows, macOS and Linux.
          Open a matrix, drag an interval, press Solve.</li>
      <li><strong>A free web calculator</strong> running the same library, for
          problems up to the sizes listed on that page.</li>
      <li><strong>A Python interface</strong>, <code>feastpy</code>, that the app
          and the calculator both call &mdash; so there is one implementation,
          not three.</li>
      <li><strong>Reproducible builds</strong> on all four platform targets,
          each checked against an analytically known spectrum.</li>
    </ul>
  </div>
  <div>
    <h2>Release notes</h2>
    <dl class="news">
      <dt>v4.0 &mdash; Feb 2020</dt>
      <dd>Faster schemes, support for polynomial problems, mixed precision,
          IFEAST (iterative inner solves) and PFEAST (distributed).</dd>
      <dt>v3.0 &mdash; Jun 2015</dt>
      <dd>Non-Hermitian problems.</dd>
      <dt>v2.1 &mdash; Feb 2013</dt>
      <dd>Adopted by Intel MKL as the Extended Eigensolver.</dd>
      <dt>v2.0 &mdash; Mar 2012</dt>
      <dd>Parallel variants.</dd>
      <dt>v1.0 &mdash; Sep 2009</dt>
      <dd>First release.</dd>
    </dl>
  </div>
</section>

<section class="panel">
  <h2>Why an interval?</h2>
  <p>Most eigensolvers answer &ldquo;give me the <em>k</em> smallest&rdquo;.
     FEAST answers &ldquo;give me everything between <em>a</em> and <em>b</em>&rdquo;,
     which is the question that actually comes up in electronic structure,
     structural vibration and stability analysis &mdash; and it parallelises
     naturally, because separate intervals are independent.</p>
  <p>The practical difficulty is knowing where to look. The desktop app and the
     calculator both bound the spectrum up front and can estimate how many
     eigenvalues an interval holds before you commit to solving it.</p>
</section>
"""

FEATURES = """
<h1>Features</h1>

<section class="panel">
  <h2>The solver</h2>
  <ul>
    <li>Standard <code>A x = &lambda; x</code> and generalized
        <code>A x = &lambda; B x</code> problems, with <code>B</code> positive
        definite.</li>
    <li>Real symmetric, complex Hermitian, complex symmetric and general
        non-Hermitian, in double precision.</li>
    <li>Polynomial problems &mdash;
        <code>(A<sub>0</sub> + &lambda;A<sub>1</sub> + &lambda;&sup2;A<sub>2</sub>)x = 0</code>
        &mdash; solved directly, without linearising into a problem of twice
        the size.</li>
    <li>Dense, sparse (CSR) and banded interfaces.</li>
    <li>IFEAST variants that solve the inner linear systems iteratively, so no
        direct factorisation &mdash; and no MKL PARDISO &mdash; is required.</li>
    <li>All eigenvalues in the interval, with per-eigenpair residuals.</li>
  </ul>
</section>

<section class="panel">
  <h2>The desktop application</h2>
  <ul>
    <li><strong>Spectrum explorer.</strong> Gershgorin bounds are computed the
        moment a matrix loads, so the whole spectrum is on screen and the search
        interval is a band you drag rather than two numbers you guess.</li>
    <li><strong>Eigenvalue count estimate.</strong> A stochastic estimate answers
        &ldquo;how many are in here?&rdquo; far faster than solving, and sizes
        the subspace <code>M0</code> for you.</li>
    <li><strong>Live convergence plot.</strong> Trace error and maximum residual
        per refinement loop, so a slow solve shows whether it is converging.</li>
    <li><strong>Cancel.</strong> Stops the computation, not just the progress
        bar.</li>
    <li><strong>Export.</strong> Eigenvalues <em>and</em> eigenvectors, as
        NumPy <code>.npz</code>, CSV or Matrix Market.</li>
    <li><strong>Copy as code.</strong> Emits the current problem as a runnable
        Python or C program, including the correct FEAST routine name and
        <code>fpm</code> settings.</li>
    <li><strong>Actionable errors.</strong> Status codes come with a suggested
        fix you can apply in one click.</li>
  </ul>
</section>

<section class="panel">
  <h2>Formats it reads</h2>
  <p>Matrix Market (<code>.mtx</code>), including the banner-less coordinate
     files FEAST itself ships, and Fortran <code>D</code> exponents such as
     <code>7.1D-19</code>. Also CSV and NumPy <code>.npy</code>/<code>.npz</code>.</p>
</section>
"""

DOCUMENTATION = """
<h1>Documentation</h1>

<section class="panel">
  <h2>The user guide</h2>
  <p>The FEAST 4.0 user guide, covering every routine, argument and
     <code>fpm</code> parameter, ships with the source as
     <code>4.0/doc/feast.pdf</code>.</p>
</section>

<section class="panel">
  <h2>Choosing a routine</h2>
  <p>The name encodes the problem. Reading it is most of the battle:</p>
  <table>
    <tr><th>Fragment</th><th>Meaning</th></tr>
    <tr><td><code>d</code> / <code>z</code></td><td>double real / double complex</td></tr>
    <tr><td><code>i</code></td><td>IFEAST: iterative inner solves, no factorisation</td></tr>
    <tr><td><code>sy</code> / <code>he</code></td><td>symmetric / Hermitian</td></tr>
    <tr><td><code>csr</code></td><td>sparse; absent means dense</td></tr>
    <tr><td><code>ev</code> / <code>gv</code></td><td>standard / generalized</td></tr>
  </table>
  <p>So <code>difeast_scsrgv</code> is double precision, iterative, sparse
     symmetric, generalized. The desktop app shows you which routine your
     settings map to, and will write the calling code for you.</p>
</section>

<section class="panel">
  <h2>The three parameters that matter</h2>
  <dl>
    <dt><code>M0</code> &mdash; subspace size</dt>
    <dd>An <em>over-estimate</em> of how many eigenvalues are in the interval.
        Too small returns <code>info=3</code> and an incomplete answer. Estimate
        the count first and size above it.</dd>
    <dt><code>fpm(2)</code> &mdash; contour points</dt>
    <dd>Quadrature points on the contour. More points improve the rational
        filter, which usually beats simply allowing more refinement loops.</dd>
    <dt><code>fpm(3)</code> &mdash; tolerance</dt>
    <dd>Stops at 10<sup>&minus;n</sup>. Tighten it if residuals are poor.</dd>
  </dl>
</section>

<section class="panel">
  <h2>Python</h2>
  <pre><code>import feastpy
r = feastpy.eigsh_interval(A, emin=0.18, emax=1.0, B=B, m0=30)
print(r.n_found, r.eigenvalues, r.residuals)</code></pre>
  <p><code>feastpy.spectral_bounds(A)</code> brackets the spectrum;
     <code>feastpy.estimate_count(A, a, b)</code> estimates how many eigenvalues
     lie between <em>a</em> and <em>b</em> without solving.</p>
</section>

<section class="panel">
  <h2>Building from source</h2>
  <p>See <code>BUILDING.md</code>. Two things catch people out: gfortran 10 and
     newer need <code>-fallow-argument-mismatch</code>, and the banded interface
     requires the separate SPIKE solver, which is not bundled.</p>
</section>
"""

def _download_table() -> str:
    """Build the platform table from downloads.json.

    Kept as data rather than markup so publishing a build is editing one JSON
    file. A platform with no file yet is shown as built and tested but not
    downloadable, which is honest -- better than a link that 404s.
    """
    import json

    cfg_path = HERE / "downloads.json"
    if not cfg_path.is_file():
        return "<p class=\"note\">No downloads configured yet.</p>"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    base = cfg.get("base", "")

    rows = []
    any_link = False
    for p in cfg.get("platforms", []):
        f = p.get("file")
        if f:
            any_link = True
            url = f if f.startswith("http") else base + f
            size = f" <span class=\"muted\">({p['size']})</span>" if p.get("size") else ""
            cell = f'<a class="button primary" href="{url}">Download</a>{size}'
        else:
            cell = '<span class="muted">not published yet</span>'
        rows.append(f"<tr><td><strong>{p['name']}</strong><br>"
                    f"<span class=\"muted\">{p.get('note', '')}</span></td>"
                    f"<td>{cell}</td></tr>")

    head = ""
    if cfg.get("version"):
        when = f" &mdash; {cfg['released']}" if cfg.get("released") else ""
        head = f"<p>Current version <strong>{cfg['version']}</strong>{when}.</p>"
    # A host-specific caveat, e.g. Google Drive interrupting large downloads
    # with a virus-scan warning. Better said up front than discovered.
    if cfg.get("notice"):
        head += f'<p class="note">{cfg["notice"]}</p>'
    # Second table: the Developer Kits, when configured. Same rules.
    dk = cfg.get("devkits", [])
    dk_rows = []
    for p_ in dk:
        f = p_.get("file")
        if f:
            url = f if f.startswith("http") else base + f
            size = f" <span class=\"muted\">({p_['size']})</span>" if p_.get("size") else ""
            cell = f'<a class="button" href="{url}">Download</a>{size}'
        else:
            cell = '<span class="muted">not published yet</span>'
        dk_rows.append(f"<tr><td><strong>{p_['name']}</strong><br>"
                       f"<span class=\"muted\">{p_.get('note','')}</span></td>"
                       f"<td>{cell}</td></tr>")
    dk_html = ""
    if dk_rows:
        dk_html = ("<h2>Developer Kits</h2>"
                   "<p>For people who link FEAST into their own code: the "
                   "libraries (serial, banded/SPIKE, and MPI/PFEAST), the "
                   "headers, all 80 of upstream's examples, and the build "
                   "scripts with every portability fix already applied. The "
                   "<strong>full-feature</strong> kits bundle Intel MKL 2021.4 "
                   "and pass all 36 upstream examples, direct solver "
                   "included.</p><table>" + "".join(dk_rows) + "</table>")

    # Checksums, when a manifest has been published alongside the site. Worth
    # doing here specifically because these downloads are hosted off-site:
    # anyone can verify what they got matches what we built, which is the one
    # guarantee a third-party host cannot give you.
    if cfg.get("checksums"):
        dk_html += (f'<h2>Verifying a download</h2><p>Every file above is '
                    f'listed with its SHA-256 in '
                    f'<a href="{cfg["checksums"]}">{cfg["checksums"]}</a>. '
                    f'To check one:</p>'
                    f'<pre><code>shasum -a 256 FEAST-windows-x64.zip   '
                    f'# macOS / Linux\n'
                    f'certutil -hashfile FEAST-windows-x64.zip SHA256  '
                    f'# Windows</code></pre>'
                    f'<p class="note">These builds are not code-signed yet, so '
                    f'macOS will refuse the first launch (right-click &rarr; '
                    f'<em>Open</em>) and Windows will show a SmartScreen '
                    f'warning. The checksums are how you confirm a file is the '
                    f'one we published in the meantime.</p>')

    tail = ""
    if not any_link:
        tail = (f'<p class="note">Builds exist and are tested on every platform '
                f'above, but none has been published for download yet. They are '
                f'produced by CI on every change and can be fetched from the '
                f'<a href="{cfg.get("releases_page", "#")}">releases page</a> '
                f'once published.</p>')
    return head + "<table>" + "".join(rows) + "</table>" + dk_html + tail


DOWNLOAD = """
<h1>Download</h1>

<section class="panel">
  <h2>Desktop application</h2>
  <p>One self-contained application &mdash; no Python, no compiler, no MKL to
     install. Every build is checked in CI against a matrix whose spectrum is
     known analytically, and the Python and GUI test suites run on all four
     platform targets before a build is produced.</p>
  __DOWNLOAD_TABLE__
  <p class="note">The builds are not code-signed yet. macOS will refuse to open
     a downloaded application until you right-click it and choose <em>Open</em>
     (or run <code>xattr -dr com.apple.quarantine FEAST.app</code>), and Windows
     will show a SmartScreen warning. Signing certificates are on the list.</p>
</section>

<section class="panel">
  <h2>What is in it</h2>
  <ul>
    <li>Every problem FEAST ships as a built-in example &mdash; from the 4&times;4
        in the user guide to a 49,192-row benzene molecule &mdash; each with the
        settings from its own <code>.in</code> file.</li>
    <li>Six views: the matrix itself, the spectrum, the rational filter and its
        contour, per-eigenvalue accuracy, the eigenvectors, and convergence.</li>
    <li>Hermitian interval searches, non-Hermitian searches over a disc in the
        complex plane, and polynomial (quadratic) problems.</li>
    <li>Every algorithmic option FEAST offers, explained in plain English.</li>
  </ul>
</section>

<section class="panel">
  <h2>Source</h2>
  <p>The solver, the Python interface, the application and this site build from
     one repository. The FEAST 4.0 sources in <code>4.0/</code> are unmodified.</p>
  <pre><code>bash build/build-spike.sh     # optional: unlocks the banded routines
bash build/build-feast.sh     # builds libfeast for this platform
bash build/run-test.sh        # checks it against a known spectrum
python gui/app.py             # runs the desktop app</code></pre>
</section>
"""

LICENSE = """
<h1>License</h1>

<section class="panel">
  <p>The FEAST solver package is distributed under the BSD licence.</p>
  <blockquote>
    <p>Copyright (c) 2009&ndash;2020, The Regents of the University of
       Massachusetts, Amherst. E. Polizzi research lab. All rights reserved.</p>
    <p>Redistribution and use in source and binary forms, with or without
       modification, are permitted provided that the following conditions are
       met:</p>
    <ol>
      <li>Redistributions of source code must retain the above copyright notice,
          this list of conditions and the following disclaimer.</li>
      <li>Redistributions in binary form must reproduce the above copyright
          notice, this list of conditions and the following disclaimer in the
          documentation and/or other materials provided with the
          distribution.</li>
      <li>Neither the name of the University nor the names of its contributors
          may be used to endorse or promote products derived from this software
          without specific prior written permission.</li>
    </ol>
    <p class="disclaimer">This software is provided by the author &ldquo;as
       is&rdquo; and any express or implied warranties, including, but not
       limited to, the implied warranties of merchantability and fitness for a
       particular purpose are disclaimed&hellip;</p>
  </blockquote>
  <p>The full text ships as <code>4.0/LICENSE</code>.</p>
</section>
"""

REFERENCES = """
<h1>References</h1>

<section class="panel">
  <h2>The method</h2>
  <ul class="refs">
    <li>E. Polizzi, <em>Density-Matrix-Based Algorithms for Solving Eigenvalue
        Problems</em>, Physical Review B, 79, 115112 (2009). The paper the
        solver is built on.</li>
    <li>P. Tang, E. Polizzi, <em>FEAST as a Subspace Iteration Eigensolver
        Accelerated by Approximate Spectral Projection</em>, SIAM Journal on
        Matrix Analysis and Applications, 35, 354&ndash;390 (2014).</li>
    <li>B. Gavin, A. Miedlar, E. Polizzi, <em>FEAST Eigensolver for Nonlinear
        Eigenvalue Problems</em>, Journal of Computational Science (2018).</li>
  </ul>
  <p class="note">Citations are given for orientation; check them against the
     user guide or the publisher before citing in your own work.</p>
</section>

<section class="panel">
  <h2>Where else FEAST appears</h2>
  <p>FEAST has been included in Intel MKL as the Extended Eigensolver since
     2013, which is often the quickest way to try it if you already link MKL.</p>
</section>
"""

CONTACT = """
<h1>Contact</h1>

<section class="panel">
  <h2>The solver</h2>
  <p>FEAST is developed by the E. Polizzi research lab at the University of
     Massachusetts, Amherst. The project's own site is
     <a href="https://www.feast-solver.org/">feast-solver.org</a>.</p>
</section>

<section class="panel">
  <h2>This distribution</h2>
  <p>The desktop application, the Python interface, the calculator and this site
     are maintained alongside the solver. Bug reports for the application are
     best raised against this repository rather than the solver itself, unless
     the numbers are wrong &mdash; in which case they belong upstream.</p>
</section>
"""

CALCULATOR = """
<h1>Free eigenvalue calculator</h1>
<p class="lead">This runs the real FEAST library &mdash; the same build the
   desktop app uses. Nothing is simulated or approximated for the web.</p>

<div id="app">
  <section class="panel">
    <h2>1. Your matrix</h2>
    <div class="row">
      <label for="sample">Start from a sample</label>
      <select id="sample">
        <option value="">(paste your own below)</option>
        <option value="laplacian1d">1-D Laplacian, n=200 (known spectrum)</option>
        <option value="system1">FEAST sample system1 (generalized)</option>
        <option value="system3">FEAST sample system3 (generalized)</option>
      </select>
      <button id="load-sample" type="button">Load</button>
    </div>
    <p class="hint">Matrix Market, or bare coordinate format
       (<code>rows cols nnz</code>, then <code>i j value</code>, or
       <code>i j re im</code> for complex). Real symmetric or complex Hermitian
       &mdash; the calculator searches an interval, so the eigenvalues must be
       real. The desktop app also searches a disc in the complex plane.</p>
    <textarea id="matrix" spellcheck="false"
      placeholder="200 200 598&#10;1 1 2.0&#10;1 2 -1.0&#10;..."></textarea>

    <details id="bwrap">
      <summary>Generalized problem: add a B matrix (A x = &lambda; B x)</summary>
      <p class="hint">B must be positive definite.</p>
      <textarea id="bmatrix" spellcheck="false"></textarea>
    </details>

    <div class="row">
      <button id="inspect" type="button">Inspect matrix</button>
      <span id="matinfo" class="status"></span>
    </div>
  </section>

  <section class="panel">
    <h2>2. Your interval</h2>
    <div class="row">
      <label for="emin">E min</label><input id="emin" type="number" step="any" value="0">
      <label for="emax">E max</label><input id="emax" type="number" step="any" value="0.02">
      <button id="estimate" type="button">How many are in here?</button>
      <span id="estinfo" class="status"></span>
    </div>
    <div class="row small">
      <label for="m0">Subspace M0</label><input id="m0" type="number" value="40" min="1">
      <label for="cp">Contour points</label><input id="cp" type="number" value="8" min="2" max="32">
      <label for="tol">Tolerance 1e-</label><input id="tol" type="number" value="12" min="1" max="16">
    </div>
  </section>

  <section class="panel">
    <h2>3. Solve</h2>
    <div class="row">
      <button id="solve" class="button primary" type="button">Solve</button>
      <span id="solveinfo" class="status"></span>
    </div>
    <div id="diagnosis" class="diagnosis" hidden></div>
    <div id="results" hidden>
      <div class="resultbar">
        <span id="summary"></span>
        <button id="download-csv" type="button">Download CSV</button>
      </div>
      <div id="plot"></div>
      <div class="tablewrap">
        <table id="eigtable"><thead><tr><th>#</th><th>eigenvalue</th><th>residual</th></tr></thead>
        <tbody></tbody></table>
      </div>
    </div>
  </section>

  <section class="panel limits">
    <h2>Free-tier limits</h2>
    <ul id="limits"><li>loading&hellip;</li></ul>
    <p>The limits are on problem size and time, not on features: the calculator
       does exactly what the desktop application does, on smaller problems. The
       app itself has no such caps.</p>
  </section>
</div>
"""

PAGES = [
    ("index.html", "Home", "FEAST eigenvalue solver: every eigenvalue in an interval, with a cross-platform desktop app and a free online calculator.", HOME),
    ("features.html", "Features", "What the FEAST solver and this distribution's desktop application do.", FEATURES),
    ("calculator.html", "Calculator", "Free online FEAST eigenvalue calculator, running the real library.", CALCULATOR),
    ("documentation.html", "Documentation", "How to choose a FEAST routine and set its parameters.", DOCUMENTATION),
    ("download.html", "Download", "Download the FEAST desktop application and source.", DOWNLOAD),
    ("compatibility.html", "Compatibility",
     "Measured results for every FEAST example on every platform we build.",
     COMPATIBILITY),
    ("license.html", "License", "FEAST is distributed under the BSD licence.", LICENSE),
    ("references.html", "References", "Papers describing the FEAST algorithm.", REFERENCES),
    ("contact.html", "Contact", "Who maintains FEAST and this distribution.", CONTACT),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    # The checksum manifest lives with the built release and is served from
    # the site. Copy it on every build: the download page links to it, and a
    # link to a file that is not there is worse than no link at all. Railway
    # regenerates the site at startup, so this runs there too.
    # The full per-example record, linked from the Compatibility page.
    record = HERE.parent / "COMPATIBILITY.md"
    if record.is_file():
        (OUT / "COMPATIBILITY.md").write_text(
            record.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"  {OUT / 'COMPATIBILITY.md'}")

    manifest = HERE.parent / "release" / "upload-these" / "SHA256SUMS.txt"
    if manifest.is_file():
        (OUT / "SHA256SUMS.txt").write_text(
            manifest.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"  {OUT / 'SHA256SUMS.txt'}")
    for href, title, desc, body in PAGES:
        extra_head = '<script defer src="calculator.js"></script>' if href == "calculator.html" else ""
        if "__DOWNLOAD_TABLE__" in body:
            body = body.replace("__DOWNLOAD_TABLE__", _download_table())
        (OUT / href).write_text(
            render(href, title, desc, body, head_extra=extra_head),
            encoding="utf-8")
        print(f"  {OUT / href}")
    print(f"{len(PAGES)} pages")


if __name__ == "__main__":
    main()
