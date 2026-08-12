# FEAST in plain English

What was in the box, what each piece does, what works where, and what to ask
Eric. No jargon that isn't explained.

---

## 1. What FEAST actually is

FEAST answers one question: **"give me every eigenvalue in this range."**

An eigenvalue is a number that describes a natural behaviour of a system — the
frequencies a bridge vibrates at, the energy levels an electron can occupy, the
modes a structure can buckle in. A big matrix might have 100,000 of them.

Most solvers answer *"give me the 10 smallest."* FEAST answers *"give me
everything between 3.0 and 4.0"* — which is what people actually want, because
that's the range their physics cares about. It does this with contour
integration: it draws a loop in the complex plane and integrates around it,
which is mathematically elegant and, usefully, easy to split across many
computers.

**FEAST is a library, not a program.** You can't run it. It's a box of parts
that a programmer wires into their own code. That's the gap this project fills:
we built the app you *can* run.

---

## 2. What was in the original download

The FEAST 4.0 package is one folder with five things in it:

| Folder | What it is | Plain English |
|---|---|---|
| `src/` | 65,000 lines of Fortran | The actual solver. The maths. |
| `include/` | 8 header files | The "menu" — 202 things you can call |
| `example/` | 80 small programs | Worked examples showing how to call it |
| `utility/` | 2 programs + 18 matrices | A ready-made runner and test data |
| `doc/` | `feast.pdf` | The manual |

That's it. No installer, no app, no interface. Downloading it gets you source
code you must compile yourself.

---

## 3. The 202 "things you can call"

FEAST offers 202 entry points, but they're really **7 families**. The names look
cryptic (`difeast_scsrgv`) but they're just labels stuck together, like a coffee
order:

> `d` = double precision · `i` = iterative · `feast` · `scsr` = sparse
> symmetric · `gv` = generalized

| Family | Count | What it's for | Plain English |
|---|---|---|---|
| **Dense** | 12 | Matrices where most entries are non-zero | Small-to-medium problems. Simple. |
| **Sparse** | 40 | Matrices that are mostly zeros | Nearly all real problems. A 100,000×100,000 matrix with only 500,000 real numbers in it. |
| **Banded** | 20 | Non-zeros only near the diagonal | A common special shape, worth optimising for |
| **Polynomial** | 30 | Problems where the answer appears squared/cubed | Damped vibrations, more complex physics |
| **PFEAST** | 62 | Split across many computers | For clusters. Same maths, many machines. |
| **RCI** | 14 | "You do the hard part" | For experts who want to supply their own inner solver |
| **Tools** | 14 | Contour shapes, setup helpers | Plumbing |

**Hermitian vs non-Hermitian** is the other split you'll see. Hermitian matrices
are "symmetric" in a specific sense and their eigenvalues are ordinary numbers
on a line — so you search an *interval*. Non-Hermitian ones have eigenvalues
scattered across the complex plane, so you search a *disc* instead. Different
maths, different routines.

---

## 4. The helpers FEAST needs

FEAST doesn't do all the work itself. It's like a recipe that assumes you own
certain appliances.

| Helper | What it does | Do we have it? |
|---|---|---|
| **BLAS/LAPACK** | Basic matrix arithmetic. Every scientific program uses one. | Yes — we use **OpenBLAS** (free, open source) |
| **MKL** | Intel's version of the above, plus **PARDISO** (a fast solver) | Optional. Free to download, 836 MB, x86 only |
| **SPIKE** | A specialist solver for *banded* matrices | **No — the download is dead** |
| **MPI** | Lets one program run across many computers | Optional, needed only for PFEAST |

Three of the four are fine. **SPIKE is the problem** — see section 7.

### Why "which BLAS" turned out to matter enormously

These are supposed to be interchangeable. They are not:

- **Apple's Accelerate** (built into every Mac) ships an *old* LAPACK. FEAST's
  non-Hermitian routines return an internal error against it. We found this only
  because we tested on real Macs. **Every macOS build we made before that was
  quietly broken** for those routines. Now macOS uses OpenBLAS too.
- **Current Intel MKL** removed some old functions FEAST still calls, so it
  won't even link. **MKL 2021.4** works.

---

## 5. What works where, and why

### The app (what you'd actually sell)

| | Windows | Linux | Mac |
|---|---|---|---|
| App runs | ✅ | ✅ | ✅ built & self-tested; **you still need to click it** |
| Finds eigenvalues correctly | ✅ | ✅ | ✅ |
| Needs anything installed? | No | No | No |

All three are self-contained: unzip and run. No Python, no compilers, nothing.

### The library, by family

| Family | Windows | Linux | Mac | **Web** | Why |
|---|---|---|---|---|---|
| Dense | ✅ | ✅ | ✅ | ✅ to 500×500 | Works everywhere |
| Sparse, real symmetric | ✅ | ✅ | ✅ | ✅ to 5,000 | Works everywhere |
| Sparse, complex Hermitian | ✅ | ✅ | ✅ | ✅ | **Fixed** — was silently solving the wrong matrix (see §9) |
| Sparse polynomial | ✅ | ✅ | ✅ | ❌ | Works everywhere via the *iterative* routine. The calculator's page just doesn't offer it yet — the backend could. |
| Banded | ✅ | ✅ | ✅ | ❌ | Needs SPIKE. Now built and tested on **all four** CI platforms including Apple Silicon. |
| Non-Hermitian (complex discs) | ✅ | ✅ | ✅ | ❌ | `feastpy` does it; the desktop app and calculator are interval-only, and complex spectra need a 2-D picture. |
| PFEAST (clusters) | builds, crashes | ✅ | untested | ❌ | For clusters. Meaningless in a browser. |

### The app's views, by platform

Everything below is in the desktop app on all three systems — same code, same
tests. The web calculator is a deliberately smaller thing.

| View | Windows | Linux | Mac | **Web** | What it shows |
|---|---|---|---|---|---|
| Matrix | ✅ | ✅ | ✅ | ❌ | The matrix itself: exact numbers below 24×24, sparsity pattern above, plus bandwidth and a symmetry audit |
| Spectrum | ✅ | ✅ | ✅ | ✅ | Where the eigenvalues are, with a draggable search interval |
| Filter & contour | ✅ | ✅ | ✅ | ❌ | **New.** The rational filter and the quadrature contour — the objects FEAST's own papers are about |
| Accuracy | ✅ | ✅ | ✅ | ❌ | **New.** Eigenvalue vs residual, with the rejected subspace slots shown hollow |
| Eigenvector | ✅ | ✅ | ✅ | ❌ | **New.** Click an eigenvalue, see its eigenvector |
| Convergence | ✅ | ✅ | ✅ | ❌ | Error per refinement loop |
| Built-in problems | 11 | 13 | 13 | 2 | FEAST's own samples. Windows ships 11: benzene is 68 MB and excluded from the bundle |
| Algorithm options + explanations | ✅ | ✅ | ✅ | ❌ | 19 options, each explained in plain English |

**Why the web column is so much emptier.** Not capability — the calculator calls
the same `feastpy`. It is that a browser session is anonymous, shared, and
time-limited: a 30-second cap and roughly two solves a second sustained across
all visitors. The desktop app owns your whole machine and can take six minutes
on bcsstk11 if you want. Everything marked ❌ above is a page nobody has built
yet, not a thing the backend cannot do.

**The web column is a UI limit, not a capability limit.** The calculator calls
the same `feastpy` as the app, so anything the app can do the backend can do —
those pages simply haven't been built. The only real web-specific limits are
size and time, below.

**Why Linux looks ahead — and mostly isn't.** There is nothing Windows or macOS
cannot do here. The differences are:

- **MKL is optional, not required.** It is a speed-up and it lets FEAST's own
  examples run unmodified. Every capability it unlocks is also reachable
  without it, through FEAST's iterative routines. Tested.
- **MKL on Windows** works, but with Intel's compiler rather than the free one
  we use. That is a toolchain choice, not a Windows limit.
- **MKL on Apple Silicon** genuinely does not exist — Intel only ships it for
  Intel chips. It does not matter, because the iterative routines cover the
  same ground.
- **MPI exists on all three** (Microsoft MPI, Homebrew, Linux packages). We
  built PFEAST on Linux only because that is where clusters live.

**Nothing important is missing on any platform.** The single real gap is banded
matrices, and that is missing *everywhere*, Linux included, because the SPIKE
package cannot be downloaded by anyone.

### What the web calculator costs to run

Measured on this machine (28 cores, OpenBLAS, no MKL), sizing the subspace from
the estimator exactly as the page does:

| Problem | Time |
|---|---|
| sparse, n=1,000 | **1.8 s** |
| sparse, n=5,000 | over 30 s — times out |
| dense, n=100 | 1.7 s |
| dense, n=300 | 9.2 s |
| "how many are in here?" (any size) | 0.05–3.4 s |

Under load, with four solves allowed at once:

| Simultaneous users | All served in | Throughput |
|---|---|---|
| 1 | 1.7 s | 0.6 solves/s |
| 4 | 1.9 s | 2.1 solves/s |
| 8 | 3.6 s | 2.2 solves/s |

**So: no, it will not eat your server.** About two solves a second sustained,
and eight people clicking at once are all served within four seconds. For a
low-traffic specialist site that is far more headroom than you need — a modest
$10/month box would cope, and the rate limit (20 requests/minute per visitor)
plus the 30-second timeout stop anyone monopolising it.

Two things make that true, and both were set deliberately:

- **Each solve gets a slice of the machine, not all of it.** FEAST is
  OpenMP-parallel and will grab every core it can see. On a server that means
  one visitor starves everyone else, so each solve is capped to
  cores ÷ concurrent-solves.
- **Only four solves run at once**; the rest queue. That is why 8 users take
  3.6 s rather than falling over.

The caps were also *wrong* until this measurement: the page advertised sparse up
to 20,000, which cannot finish inside the 30-second limit. A user would pick an
allowed size and get a timeout. Sparse is now capped at 5,000. Cost depends
mostly on **how many eigenvalues are in your interval**, not on how big the
matrix is, so no size cap can guarantee completion — the timeout is the real
guard.

Running the server against MKL would raise these ceilings a lot, because it
unlocks the direct PARDISO solver instead of the iterative one. That is not yet
verified: the server's numpy is itself linked against a newer MKL, and two MKL
versions cannot coexist in one process, so it needs a dedicated environment.

### Why these aren't tested automatically

Every time we change the code, GitHub runs the whole test suite on fresh
Windows, Linux and Mac machines, free. Adding MKL and MPI would mean downloading
**about 1 GB extra onto every one of those machines, on every change** —
836 MB for MKL, 205 MB for MPI — to build a 2.3 MB file. Minutes added to every
run, for parts the app doesn't use. So those two are built by hand on the Linux
box instead, and the recipe is written down in `BUILDING-COMPLETE.md`.

---

## 6. What we built on top

| | What it is |
|---|---|
| **The desktop app** | Open a matrix, drag a range, press Solve. Windows/Mac/Linux. |
| **`feastpy`** | A Python layer so all 202 routines can be called without writing C |
| **The website** | A copy of feast-solver.org's structure, for this version |
| **The free calculator** | Runs the real solver in a browser, capped by problem size |
| **Licensing** | Signed keys, verified offline. Currently switched off. |

The app, the calculator and any future script all call the *same* code — so
there's one implementation to keep correct, not three.

---

## 7. What to ask Eric

**The one that actually blocks us:**

1. **Can you give us SPIKE?** spike-solver.org's download links all return
   "404 not found" — the files are gone. No source is published anywhere. It's
   his lab's package, so he probably has it on a hard drive. Without it, 20
   routines and 10 examples can't be built by anyone, including people
   downloading FEAST today. **He may not know the links are broken.**

**Decisions only he can make:**

2. **Whose product is this?** His name, ours, or joint? That changes the
   website, the licence, and who takes payment.
3. **Should it be paid at all?** FEAST is free and BSD-licensed. We'd be selling
   the *application*, not the maths. He may prefer it free, or free for
   academics and paid for industry.
4. **How do payments work?** We can email licence keys manually. Fine at low
   volume. University buyers usually need an invoice and a purchase order, not
   Venmo.
5. **Is v4.0 still current?** It's from February 2020 — six years old. Is a v5.0
   coming? That changes what "includes updates" should mean.
6. **Ship MKL, or not?** It makes some things faster and unlocks sparse
   polynomial, but Intel's redistribution terms are stricter than FEAST's BSD,
   and it doesn't work on Apple Silicon.
7. **Does anyone actually want this?** He knows the user community. Five minutes
   of his opinion is worth more than months of guessing.

**Worth mentioning, because it affects his users too:**

8. Apple's built-in maths library **breaks FEAST's non-Hermitian routines**.
   Anyone building FEAST on a Mac the obvious way gets a broken build with no
   warning. He'd probably want to document that.
9. FEAST doesn't compile with modern gfortran without an extra flag
   (`-fallow-argument-mismatch`), and nothing in the docs says so.
10. Current Intel MKL no longer has functions FEAST calls, so `MKL=yes` fails
    to link against anything recent.
11. **A real bug in `include/feast_tools.h`.** Four routines are declared with
    seven arguments where the Fortran defines eight — the `fpm18` ellipse-ratio
    argument is missing from `zfeast_gcontour`, `cfeast_gcontour`,
    `zfeast_grational` and `cfeast_grational`:

    ```
    header:  zfeast_gcontour_(Emid, r, fpm2, fpm17,        fpm19, Zne, Wne)
    Fortran: zfeast_gcontour (Emid, r, fpm8, fpm17, fpm18, fpm19, Zne, Wne)
    ```

    Everything after `fpm17` shifts by one, so a C caller has the rotation angle
    read out of the ellipse-ratio slot, a pointer read as the rotation angle,
    and the two output pointers read from past the end of the arguments actually
    supplied — FEAST then writes the contour through whatever those bytes hold.
    That is memory corruption, not a wrong number. The Fortran side is correct:
    called properly, a radius-1 circle puts every node at distance exactly
    1.000000. Fortran users are unaffected; C users of these four are not.
12. **`fpm(17)` is undocumented but still required.** Table 1 of the guide jumps
    from `i=16` to `i=18`, and `feast_tools.f90` comments that `fpm(17)` is
    "deprecated in v4.0" — yet it remains a mandatory argument of the contour
    and rational-filter utilities, where it selects the integration rule for the
    non-Hermitian contour. Callers have to know to pass `fpm(16)`'s value into a
    slot the manual never mentions.

---

## 8. What reading the manual turned up

The v4.0 User Guide (arXiv 2002.04807) was read against the source, all 36
example programs, the 12 shipped problems and the original Linux driver. Five
things came out of it that changed the product.

**Three bugs in our own code, all of the silent kind.**

1. **We were solving the wrong matrix.** Handed a complex Hermitian sparse
   matrix, the solver built its arrays as real and threw the imaginary part
   away. FEAST then solved the real part — a different matrix — and returned
   `info=0`, success. Measured on a 40×40 case: 2 eigenvalues returned where 5
   exist, none within 0.65 of a true one. Now routed to the complex routine:
   5 of 5, error 3×10⁻¹⁴. This is what the desktop app and the web calculator
   both use.
2. **We were overriding FEAST's own defaults.** `feastinit` does not fill in
   defaults — it sets all 64 parameters to a marker meaning *"let the routine
   decide"*, and different routines decide differently: 20 refinement loops for
   FEAST, 50 for IFEAST. We wrote 20 unconditionally. FEAST's own `system2`
   sample stopped short at `info=2` with a residual of 2.6×10⁻⁶; left alone it
   converges to 6×10⁻¹³.
3. **A "guaranteed" bound that wasn't.** The spectrum bracket used an iterative
   solver's approximate answer as if exact, so it could cut *inside* the real
   spectrum. Windows CI caught it at 1.332 against a true maximum of 1.3328.

**Two bugs in FEAST itself, worth sending to Eric** (§7, items 11–12): four
routines are declared in the C header with seven arguments where the Fortran
has eight, which corrupts memory for any C caller; and `fpm(17)` is required by
those routines but appears nowhere in the manual.

**And the thing that reshaped the GUI.** FEAST ships a routine,
`dfeast_rational`, that computes nothing you can solve with. Its only purpose
is to let you *plot the filter* — the function that is ~1 inside your search
interval and ~0 outside. That is the object the whole method is built on, and
the app never showed it. Measured on [0,1]: 4 contour points separate inside
from outside by a factor of 70, 8 points by 18,000, 16 points by 56 million.
One picture explains why more contour points help, why the subspace must be
bigger than the answer, and why an interval edge must never sit on an
eigenvalue — the filter is exactly 0.5 there, so such an eigenvalue is counted
half in and half out.

---

## 9. Glossary

| Term | Plain English |
|---|---|
| **Eigenvalue** | A number describing a natural behaviour — a frequency, an energy level |
| **Matrix** | A grid of numbers describing a system |
| **Dense / sparse** | Mostly non-zeros / mostly zeros |
| **Hermitian** | A symmetric-ish matrix whose eigenvalues are ordinary numbers |
| **Library** | Code other programs use; you can't run it directly |
| **Compile / build** | Turning source code into a program that runs |
| **BLAS / LAPACK** | Standard maths building blocks every scientific program uses |
| **MKL** | Intel's fast version of those, plus extras |
| **PARDISO** | A fast solver inside MKL |
| **SPIKE** | A specialist solver for banded matrices |
| **MPI** | Software for running one program across many computers |
| **CI** | Robots that rebuild and retest everything on every change |
| **Toolchain** | The set of tools needed to build software |
| **Linking** | Connecting your program to the libraries it uses |
| **ABI** | The fine print of how compiled code fits together. Mismatches crash. |
