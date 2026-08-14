"""The Compatibility page.

Kept in its own module because it is the page most likely to go stale: every
number on it is a measurement, and a measurement that quietly stops being true
is worse than no claim at all. The full per-example record lives in
COMPATIBILITY.md, which the page links; this is the readable summary.

The audience is a numerical person deciding whether to trust the build. So the
page leads with what does not work, and says how each number was obtained --
CI, or a physical machine.
"""

COMPATIBILITY = """
<h1>What runs where</h1>

<p class="lead">Every claim below is measured, not inferred. FEAST ships 36
serial example programs and 44 distributed ones; we run all of them on every
platform we build, and publish the results whether or not they flatter us.
The full per-example record is in
<a href="COMPATIBILITY.md">COMPATIBILITY.md</a>.</p>

<section class="panel">
  <h2>Upstream's own examples</h2>
  <p>Not our tests &mdash; FEAST's, unmodified, compiled against our build.
     That is a stronger claim than &ldquo;our test suite passes&rdquo;.</p>
  <table>
    <tr><th>Build</th><th>Windows</th><th>Linux</th><th>macOS Intel</th><th>Apple Silicon</th></tr>
    <tr>
      <td><strong>Standard</strong><br><span class="muted">OpenBLAS, iterative inner solver</span></td>
      <td>34 / 36</td><td>34 / 36</td><td>34 / 36</td><td>34 / 36</td>
    </tr>
    <tr>
      <td><strong>Full-feature</strong><br><span class="muted">with Intel MKL 2021.4</span></td>
      <td><strong>36 / 36</strong></td><td><strong>36 / 36</strong></td><td><strong>36 / 36</strong></td>
      <td><span class="muted">via Rosetta 2 &mdash; see below</span></td>
    </tr>
    <tr>
      <td><strong>PFEAST</strong><br><span class="muted">44 distributed examples, 2 ranks</span></td>
      <td>40 / 44</td><td>40 / 44</td><td>40 / 44</td><td>40 / 44</td>
    </tr>
  </table>
  <p class="note">The standard and PFEAST rows are <em>identical on every
     platform, example by example</em> &mdash; not merely equal in total.</p>
</section>

<section class="panel">
  <h2>What does not pass, and why</h2>
  <p>Two of the 36 serial examples and four of the 44 distributed ones fail,
     and they are the same problem in both cases: the polynomial
     <code>scsrpev</code> programs. They need a <em>direct</em> sparse solver
     to converge at the tolerance they ask for, and the standard build has
     none &mdash; every inner system is solved iteratively.</p>
  <p>This is not a platform difference. They fail identically on Windows,
     Linux and both Macs, and they pass on all three Intel-capable platforms
     once MKL supplies the direct solver. The polynomial <em>capability</em>
     works everywhere regardless: the desktop application solves the same
     quadratic problem to a residual of 9.4&times;10<sup>-7</sup> by sizing the
     subspace appropriately rather than inheriting the example's settings.</p>
</section>

<section class="panel">
  <h2>Apple Silicon</h2>
  <p>Everything native except one thing: <strong>Intel does not build MKL for
     ARM</strong>, and will not. Apple Silicon therefore uses OpenBLAS and
     FEAST's iterative routines, which reach 34 of the 36 examples &mdash; the
     same as every other platform's standard build.</p>
  <p>For the remaining two, the macOS Intel full-feature kit runs under
     <strong>Rosetta 2</strong>. We measured this on an M1: the kit's own
     accuracy test, translated, passes at
     5.2&times;10<sup>-16</sup>. It works because MKL 2021.4 predates the
     translation block Intel added in 2022 &mdash; and 2021.4 is also the
     newest release that still contains the sparse routines FEAST calls, so
     the version FEAST needs is exactly the version that still runs
     translated.</p>
  <p class="note">Do not link Apple's Accelerate framework. Its LAPACK is old
     enough that FEAST's non-Hermitian routines return <code>info=-3</code>,
     and the Hermitian path keeps working, so the failure looks like a FEAST
     bug rather than a BLAS choice.</p>
</section>

<section class="panel">
  <h2>Routine coverage</h2>
  <p>Identical on all four platforms: <strong>140 of 140</strong> non-MPI
     entry points are present in the shipped library and callable from
     <code>feastpy</code>. The 60 PFEAST routines live in a separate library
     (<code>libpfeast</code>) because they require MPI.</p>
  <table>
    <tr><th>Family</th><th>Declared</th><th>In the shipped library</th></tr>
    <tr><td>Sparse CSR</td><td>40</td><td>40</td></tr>
    <tr><td>Polynomial</td><td>30</td><td>30</td></tr>
    <tr><td>Banded (via SPIKE)</td><td>20</td><td>20</td></tr>
    <tr><td>Tools &amp; contours</td><td>14</td><td>14</td></tr>
    <tr><td>RCI</td><td>14</td><td>14</td></tr>
    <tr><td>Dense Hermitian</td><td>12</td><td>12</td></tr>
    <tr><td>Non-Hermitian</td><td>10</td><td>10</td></tr>
    <tr><td>PFEAST (MPI)</td><td>60</td><td>separate library</td></tr>
  </table>
</section>

<section class="panel">
  <h2>The 13 built-in problems</h2>
  <p>Every problem FEAST ships is built into the application, with the
     settings from its own <code>.in</code> file. Four are limited by the
     absence of a direct solver rather than by any platform, and each says so
     on its own entry in the application rather than failing silently.</p>
  <table>
    <tr><th>Problem</th><th>Size</th><th>Result</th></tr>
    <tr><td>Hello world (the 4&times;4 from the user guide)</td><td>4</td><td>2 eigenvalues, residual 3e-14</td></tr>
    <tr><td>system1 &mdash; real symmetric, generalized</td><td>1,671</td><td>16, residual 7.7e-14</td></tr>
    <tr><td>system2 &mdash; complex Hermitian</td><td>600</td><td>30, residual 6.0e-13</td></tr>
    <tr><td>system3 &mdash; non-Hermitian (disc search)</td><td>1,671</td><td>16, residual 5.7e-14</td></tr>
    <tr><td>system4 &mdash; complex symmetric</td><td>801</td><td>6, residual 9.7e-13</td></tr>
    <tr><td>system5 &mdash; quadratic polynomial</td><td>1,000</td><td>20, residual 9.4e-07</td></tr>
    <tr><td>Carbon nanotube</td><td>12,450</td><td>100, residual 3.5e-13 (~2.5 min)</td></tr>
    <tr><td>Sodium cluster Na5</td><td>5,832</td><td>100, residual 1.5e-13 (~40 s)</td></tr>
    <tr><td>Structural stiffness bcsstk11</td><td>1,473</td><td>800, residual 2.4e-13 (~6 min)</td></tr>
    <tr><td>Carbon monoxide</td><td>8,478</td><td class="muted">needs a direct solver</td></tr>
    <tr><td>Benzene C<sub>6</sub>H<sub>6</sub></td><td>49,192</td><td class="muted">needs a direct solver</td></tr>
    <tr><td>Grcar matrix</td><td>100</td><td class="muted">needs a direct solver</td></tr>
    <tr><td>Quantum chemistry qc324</td><td>324</td><td class="muted">converges slowly</td></tr>
  </table>
</section>

<section class="panel">
  <h2>How these were measured</h2>
  <p>The standard builds and the three full-feature builds are compiled and
     exercised by continuous integration on Windows, Linux, macOS Intel and
     Apple Silicon on every change, and the packaged application self-tests in
     a stripped environment before it is published. The Apple Silicon Rosetta
     result and the Windows PFEAST result were measured on physical machines,
     because no CI runner could have told us.</p>
  <p>Three toolchain defects had to be fixed to reach these numbers, and all
     three are documented with their fixes in the Developer Kits: four wrong
     prototypes in FEAST's own <code>feast_tools.h</code>, a compiler-directive
     gap that silently corrupts <code>MPI_IN_PLACE</code> under gfortran with
     Microsoft MPI, and a complex-return ABI mismatch against MKL.</p>
</section>
"""
