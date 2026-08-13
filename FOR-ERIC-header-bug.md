# FEAST 4.0: four C prototypes disagree with the Fortran they declare

**Summary.** In `4.0/include/feast_tools.h`, four routines are declared with one
argument fewer than the Fortran subroutine they call. The missing argument is
`fpm18`, the ellipse ratio. Any C program calling these gets its remaining
arguments shifted by one position, and because the two shifted arguments are
*output pointers*, FEAST writes results through addresses the caller never
supplied. This is memory corruption, not a wrong number, and it produces no
compiler warning.

Fortran callers are unaffected — the Fortran side is correct and internally
consistent. This is a C-header-only problem.

We hit it while building a GUI on top of FEAST 4.0, because our Python binding
derives its call signatures from these headers.

---

## 1. The four routines

All in `4.0/include/feast_tools.h`, against `4.0/src/kernel/feast_tools.f90`:

| Routine | header line | C args | Fortran line | Fortran args |
|---|---|---|---|---|
| `zfeast_gcontour` | 36 | 7 | 677 | **8** |
| `zfeast_grational` | 40 | 8 | 1223 | **9** |
| `cfeast_grational` | 41 | 8 | 1259 | **9** |
| `cfeast_gcontour` | 45 | 7 | 762 | **8** |

Side by side:

```c
/* include/feast_tools.h:36 */
extern void zfeast_gcontour_(double *Emid, double *r, int *fpm2, int *fpm17,
                             int *fpm19, double *Zne, double *Wne);
```
```fortran
! src/kernel/feast_tools.f90:677
subroutine zfeast_gcontour(Emid, r, fpm8, fpm17, fpm18, fpm19, Zne, Wne)
```

`fpm18` is absent from the C declaration, and the third argument is named
`fpm2` where the Fortran calls it `fpm8`.

**Note there are two copies of each mistake.** The header declares the mangled
symbol with `extern` and then defines an inline C wrapper that forwards to it.
Both carry the same signature, so the fix touches **eight** lines:

| | `extern` declaration | inline wrapper |
|---|---|---|
| `zfeast_gcontour` | line 36 | line 71 |
| `cfeast_gcontour` | line 45 | line 74 |
| `zfeast_grational` | line 40 | line 89 |
| `cfeast_grational` | line 41 | line 92 |

---

## 2. Why it corrupts memory rather than returning a wrong answer

Fortran passes everything by reference, so every argument is a pointer and
nothing about the call is type-checked across the language boundary. The C
caller pushes 7 arguments; the Fortran reads 8. Every argument after the
missing one is therefore off by one position:

| Fortran expects | receives (from a C caller) |
|---|---|
| `fpm18` — ellipse ratio | the caller's `fpm19` (rotation angle) |
| `fpm19` — rotation angle | the caller's `Zne` **pointer**, read as an integer |
| `Zne` — output array | the caller's `Wne` pointer |
| `Wne` — output array | whatever lies beyond the arguments actually pushed |

The last row is the dangerous one. `Wne` is an **output**: FEAST writes
`fpm8` complex weights through it. With nothing valid there, it writes through
a stale register or stack slot. The usual outcomes are a segfault or silent
corruption of an unrelated variable, depending on the platform's calling
convention and the compiler's mood.

---

## 3. The Fortran is correct — verified

Called with the true eight-argument signature, the routine behaves exactly as
its own comments promise:

| Call | Result |
|---|---|
| radius-1 circular contour, 16 nodes | every node at distance `1.000000` from the centre |
| `fpm18 = 30` | vertical/horizontal ratio `0.288` (0.30 requested) |
| `fpm19 = 45` | bounding box square, as a 45° rotation should give |
| `zfeast_grational` inside the disc | \|f\| = `1.000000` |
| …outside the disc | \|f\| = `1.6e-05` |

So nothing needs changing in `feast_tools.f90`. Only the header is wrong.

---

## 4. Evidence this is a copy-paste slip, not a deliberate API change

We considered whether `fpm18` had been intentionally retired from these
routines. Three things say otherwise.

**(a) The declaration is a renamed copy of the Hermitian one.** Compare the
Hermitian contour generator, which is correct, with the general one:

```
Hermitian  header: zfeast_contour_ (Emin, Emax, fpm2, fpm16, fpm18,        Zne, Wne)   7
Hermitian  F90:    zfeast_contour  (Emin, Emax, fpm2, fpm16, fpm18,        Zne, Wne)   7   OK
General    header: zfeast_gcontour_(Emid, r,    fpm2, fpm17,        fpm19, Zne, Wne)   7
General    F90:    zfeast_gcontour (Emid, r,    fpm8, fpm17, fpm18, fpm19, Zne, Wne)   8   MISMATCH
```

The general declaration keeps the Hermitian version's **seven-slot shape** and
its argument name `fpm2` — which is the *half-contour* point count and belongs
only to the Hermitian routine — with `16` and `18` bumped to `17` and `19`. It
reads as the Hermitian line copied, names edited, and the extra argument never
inserted.

**(b) FEAST's own Fortran passes all eight.** In the kernel and throughout the
banded sources:

```fortran
call zfeast_gcontour(Emid, r, fpm(8), fpm(16), fpm(18), fpm(19), Zne, Wne)
```

If `fpm18` were being retired from this interface, the internal callers would
not still be supplying it.

**(c) The Hermitian twin kept it.** A deliberate removal of the ellipse-ratio
argument would have applied to `zfeast_contour` too. It did not.

---

## 5. It is exactly these four, and no others

We compared every C prototype in `4.0/include` against the Fortran subroutine
it names. Of **202** routines declared in both languages, **4** disagree in
argument count — the four above. This is a localised slip, not a systematic
drift between the two sides.

The check is a single script, included in our repository as
`tools/check_headers.py`:

```bash
python tools/check_headers.py /path/to/FEAST/4.0
```

Output:

```
[KNOWN] zfeast_gcontour_  C declares 7, Fortran defines 8
       C   (feast_tools.h):   Emid, r, fpm2, fpm17, fpm19, Zne, Wne
       F90 (feast_tools.f90): Emid, r, fpm8, fpm17, fpm18, fpm19, Zne, Wne
   ... (3 more)

compared 202 routines declared in both C and Fortran: 0 new mismatch(es), 4 known
```

It needs only Python and a FEAST source tree, and might be worth running in
your own release process — nothing else checks these two sides agree, and they
are maintained by hand.

---

## 6. Suggested fix

Insert the missing parameter in all eight places. For `zfeast_gcontour`:

```diff
-extern void zfeast_gcontour_(double *Emid, double *r, int *fpm2, int *fpm17,
-                             int *fpm19, double *Zne, double *Wne);
+extern void zfeast_gcontour_(double *Emid, double *r, int *fpm8, int *fpm17,
+                             int *fpm18, int *fpm19, double *Zne, double *Wne);

-void zfeast_gcontour(double *Emid, double *r, int *fpm2, int *fpm17,
-                     int *fpm19, double *Zne, double *Wne){
-     zfeast_gcontour_(Emid, r, fpm2, fpm17, fpm19, Zne, Wne);
+void zfeast_gcontour(double *Emid, double *r, int *fpm8, int *fpm17,
+                     int *fpm18, int *fpm19, double *Zne, double *Wne){
+     zfeast_gcontour_(Emid, r, fpm8, fpm17, fpm18, fpm19, Zne, Wne);
 }
```

and the same for `cfeast_gcontour`, `zfeast_grational`, `cfeast_grational`,
whose Fortran signatures are:

```fortran
cfeast_gcontour (Emid, r, fpm8, fpm17, fpm18, fpm19, Zne, Wne)
zfeast_grational(Emid, r, fpm8, fpm17, fpm18, fpm19, Eig, M0, f)
cfeast_grational(Emid, r, fpm8, fpm17, fpm18, fpm19, Eig, M0, f)
```

Renaming `fpm2` to `fpm8` is cosmetic but worth doing at the same time, since
`fpm2` names a different parameter.

This is a source-incompatible change for any C code already calling these — but
such code cannot be working today, so there is nothing to preserve.

---

## 7. A related documentation gap: `fpm(17)`

While tracing this we could not find `fpm(17)` documented. In the v4.0 User
Guide (arXiv 2002.04807), Table 1 runs `i=16` then jumps to `i=18`.
`feast_tools.f90` comments that `fpm(17)` is *"deprecated in v4.0"* and the
block that used to set it is commented out.

But it remains a **required argument** of all four routines above, where it
selects the integration rule for the non-Hermitian contour, and the kernel
passes `fpm(16)` into that slot:

```fortran
call zfeast_gcontour(Emid, r, fpm(8), fpm(16), fpm(18), fpm(19), Zne, Wne)
```

So a caller has to know to pass `fpm(16)`'s value into a parameter the manual
never mentions, whose name suggests a different (retired) parameter. Worth a
line in the guide, or renaming the argument to `fpm16` to match what is
actually expected.

---

## 8. What we did on our side

We could not wait for a fix, so our Python binding overrides the four
declarations with the true Fortran signatures rather than patching your header
(`python/feastpy/raw.py`, `_HEADER_CORRECTIONS`). Nine regression tests assert
the resulting geometry — that a circular contour really is circular, that the
ratio flattens it, that the rotation turns it — because a wrong argument order
still *runs*, and only the numbers catch it.

Happy to send a patch against `feast_tools.h` if that is useful.

---

## 9. A second finding: PFEAST on Windows, diagnosed and fixed

While porting PFEAST we found that `MPI_ALLREDUCE(MPI_IN_PLACE, …)` — which
PFEAST calls at 222 sites — silently corrupts data when the caller is compiled
with mingw gfortran against Microsoft MPI, then crashes at a later collective.
A five-line reproducer with no FEAST code returns zeros instead of the
reduction.

The mechanism is a compiler-directive gap, not a FEAST bug: MS-MPI recognises
the Fortran `MPI_IN_PLACE` by the *address* of a variable in
`COMMON /MPIPRIV1/`, which its `mpif.h` marks

    !DEC$ ATTRIBUTES DLLIMPORT :: /MPIPRIV1/

Only Intel Fortran honours `!DEC$`; gfortran allocates its own private copy of
the COMMON block, so the runtime never sees the sentinel address it expects and
treats it as a real buffer.

The fix is a 20-line interception shim, included in our distribution as
`build/msmpi_inplace_compat.c`: it defines `mpi_allreduce_`, compares the send
buffer against the program's own sentinel, and forwards to the C API with the
C `MPI_IN_PLACE`. With it, PFEAST runs 40 of its 44 examples on Windows —
identical to Apple Silicon. Anyone building PFEAST on Windows with the free
toolchain needs this; it may be worth a note in the guide, since nothing about
the failure points at the actual cause.
