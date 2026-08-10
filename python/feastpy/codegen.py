"""Emitting the current problem as source code.

A GUI that cannot show its work is a dead end for scientific users: results
have to be reproducible, scriptable, and citable. This turns whatever is on
screen into a runnable program, so the app is an on-ramp to the library rather
than a walled garden.

Picking the right FEAST routine and populating fpm() is also the part users get
wrong by hand -- the name encodes precision, symmetry, storage, and whether the
inner solves are direct or iterative (d/z, sy/he, ev/gv, dense/csr, ifeast).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ProblemSpec:
    """Everything needed to reproduce a solve."""

    n: int
    sparse: bool = True
    complex: bool = False
    generalized: bool = False
    uplo: str = "U"
    emin: float = 0.0
    emax: float = 1.0
    m0: int = 40
    contour_points: int = 8
    tol_exponent: int = 12
    max_loops: int = 20
    iterative: bool = True          # IFEAST: no MKL-PARDISO in an OpenBLAS build
    matrix_path: Optional[str] = None
    b_path: Optional[str] = None


def routine_name(spec: ProblemSpec) -> str:
    """The FEAST routine this problem maps to.

    d/z      double real / double complex
    i        IFEAST: iterative inner solves (no PARDISO needed)
    sy/he    symmetric / Hermitian
    csr      sparse; absent means dense
    ev/gv    standard / generalized
    """
    prefix = "z" if spec.complex else "d"
    if spec.sparse and spec.iterative:
        prefix += "i"
    kind = "he" if spec.complex else "sy"
    tail = "gv" if spec.generalized else "ev"
    if spec.sparse:
        # sparse spells symmetric/Hermitian as scsr/hcsr
        kind = "hcsr" if spec.complex else "scsr"
        return f"{prefix}feast_{kind}{tail}"
    return f"{prefix}feast_{kind}{tail}"


def to_python(spec: ProblemSpec) -> str:
    """A runnable script using feastpy."""
    load_a = (f'A = matrixio.load_matrix(r"{spec.matrix_path}")'
              if spec.matrix_path else
              "A = ...  # your matrix: dense ndarray or scipy sparse")
    if spec.generalized:
        load_b = (f'B = matrixio.load_matrix(r"{spec.b_path}")'
                  if spec.b_path else
                  "B = ...  # mass matrix, must be positive definite")
    else:
        load_b = "B = None"

    fn = "eigsh_interval" if spec.sparse else "eigh_interval"
    uplo_line = f'\n    uplo="{spec.uplo}",' if spec.sparse else ""

    return f'''"""Reproduces the solve set up in the FEAST desktop app.

Requires the feastpy package and a built libfeast (see BUILDING.md); point
FEAST_LIBRARY at the shared library if it is not beside the package.
"""
import numpy as np
import feastpy
from feastpy import matrixio

{load_a}
{load_b}

result = feastpy.{fn}(
    A,
    emin={spec.emin!r},
    emax={spec.emax!r},
    B=B,
    m0={spec.m0},                    # subspace size: over-estimate the count
    contour_points={spec.contour_points},
    tol_exponent={spec.tol_exponent},          # stop at 1e-{spec.tol_exponent}
    max_loops={spec.max_loops},{uplo_line}
)

print(f"info={{result.info}} ({{result.message}})")
print(f"found {{result.n_found}} eigenvalues in {{result.loops}} loop(s)")
for i, (lam, res) in enumerate(zip(result.eigenvalues, result.residuals), 1):
    print(f"{{i:4d}}  {{lam:.15g}}  residual {{res:.2e}}")

# result.eigenvectors is n x n_found, one column per eigenvalue.
# feastpy.save_results("out.npz", result, "npz")
'''


def to_c(spec: ProblemSpec) -> str:
    """A C program calling FEAST directly, with the matrix left to fill in."""
    fn = routine_name(spec)
    real = "double"
    val_t = "double" if not spec.complex else "double _Complex"
    header = "feast_sparse.h" if spec.sparse else "feast_dense.h"

    if spec.sparse:
        decls = f"""    /* --- your matrix, CSR, 1-based indices, UPLO='{spec.uplo}' --------------- */
    int    *isa = malloc((N + 1) * sizeof(int));   /* row pointers, isa[0] = 1 */
    int    *jsa = malloc(nnz * sizeof(int));       /* column indices, 1-based  */
    {val_t} *sa  = malloc(nnz * sizeof(*sa));      /* values                   */
    /* TODO: fill isa, jsa, sa */"""
        b_decls = ("""
    int    *isb = malloc((N + 1) * sizeof(int));
    int    *jsb = malloc(nnz_b * sizeof(int));
    double *sb  = malloc(nnz_b * sizeof(*sb));
    /* TODO: fill isb, jsb, sb (B must be positive definite) */"""
                   if spec.generalized else "")
        a_args = "sa, isa, jsa"
        b_args = ", sb, isb, jsb" if spec.generalized else ""
    else:
        decls = f"""    /* --- your matrix, column-major, leading dimension N --------------------- */
    {val_t} *A = malloc((size_t)N * N * sizeof(*A));
    /* TODO: fill A */"""
        b_decls = ("""
    double *B = malloc((size_t)N * N * sizeof(*B));
    /* TODO: fill B (must be positive definite) */"""
                   if spec.generalized else "")
        a_args = "A, &N"
        b_args = ", B, &N" if spec.generalized else ""

    nnz_note = "    int nnz = 0;   /* TODO: number of stored nonzeros */\n" if spec.sparse else ""
    nnz_b_note = ("    int nnz_b = 0; /* TODO: nonzeros in B */\n"
                  if spec.sparse and spec.generalized else "")

    ifeast_note = ("""
 * Uses the IFEAST variant (the 'i'): the inner linear systems are solved
 * iteratively, so no MKL-PARDISO is required. Drop the 'i' if you build
 * against MKL and want the direct solver.""" if spec.sparse and spec.iterative else "")

    return f'''/* Reproduces the solve set up in the FEAST desktop app.
 *
 * Build (adjust paths):
 *   gcc -O2 -o solve solve.c -I<feast>/4.0/include \\
 *       <feast>/4.0/lib/<arch>/libfeast.a -lopenblas -lgfortran -fopenmp -lm{ifeast_note}
 */
#include <stdio.h>
#include <stdlib.h>
#include "feast.h"
#include "{header}"

int main(void) {{
    int N = {spec.n};
{nnz_note}{nnz_b_note}
{decls}{b_decls}

    /* --- FEAST parameters --------------------------------------------------- */
    int fpm[64];
    feastinit(fpm);
    fpm[0]  = 1;    /* fpm(1)  print runtime status          */
    fpm[1]  = {spec.contour_points};    /* fpm(2)  contour quadrature points     */
    fpm[2]  = {spec.tol_exponent};   /* fpm(3)  stopping tolerance, 1e-{spec.tol_exponent}      */
    fpm[3]  = {spec.max_loops};   /* fpm(4)  max refinement loops          */

    char   UPLO  = '{spec.uplo}';
    {real} Emin  = {spec.emin!r};
    {real} Emax  = {spec.emax!r};
    int    M0    = {spec.m0};      /* over-estimate of the eigenvalue count */

    {real} *lambda = malloc(M0 * sizeof(*lambda));
    {val_t} *q     = malloc((size_t)N * M0 * sizeof(*q));
    {real} *res    = malloc(M0 * sizeof(*res));

    double epsout;
    int loop, M, info;

    {fn}(&UPLO, &N, {a_args}{b_args}, fpm, &epsout, &loop,
        &Emin, &Emax, &M0, lambda, q, &M, res, &info);

    if (info != 0) {{
        fprintf(stderr, "FEAST failed: info=%d\\n", info);
        return 1;
    }}
    printf("found %d eigenvalues in %d loop(s)\\n", M, loop);
    for (int i = 0; i < M; i++)
        printf("%4d  %.15g  residual %.2e\\n", i + 1, lambda[i], res[i]);
    return 0;
}}
'''


GENERATORS = {"Python (feastpy)": to_python, "C": to_c}
