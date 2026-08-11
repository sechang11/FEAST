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

| Family | Windows | Linux | Mac | Why |
|---|---|---|---|---|
| Dense | ✅ | ✅ | ✅ | Works everywhere |
| Sparse (iterative) | ✅ | ✅ | ✅ | Works everywhere |
| Sparse polynomial | ✅ | ✅ | ✅ | Works everywhere using FEAST's *iterative* routine. Only the shipped **example** needs MKL, because it calls the direct one. |
| Banded | ❌ | ❌ | ❌ | Needs SPIKE, which nobody can download — **including on Linux**. Not a platform problem. |
| PFEAST (clusters) | ⚠️ | ✅ | ⚠️ | Needs MPI, which exists on all three. Only built and tested on Linux so far — effort, not a limit. Not a desktop feature anyway. |

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

---

## 8. Glossary

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
