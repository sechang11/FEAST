/* Numerical smoke test for a freshly built libfeast.
 *
 * Solves the standard symmetric eigenproblem for the 1-D Laplacian
 * tridiag(-1, 2, -1) of order N, whose eigenvalues are known in closed form:
 *
 *     lambda_k = 2 - 2*cos(k*pi/(N+1)),   k = 1..N
 *
 * so we can check FEAST's output against exact values rather than just
 * checking that the library links.
 */
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "feast.h"
#include "feast_dense.h"

#define N 100

int main(void) {
    static double A[N * N];
    double Emin = 0.0, Emax = 0.05;   /* expect 7 eigenvalues in here */
    int M0 = 20;

    int fpm[64], loop, mode, info, i, k;
    double epsout;
    double *lambda = malloc(M0 * sizeof(double));
    double *q      = malloc(N * M0 * sizeof(double));
    double *res    = malloc(M0 * sizeof(double));
    char UPLO = 'F';
    int n = N, lda = N;

    for (i = 0; i < N * N; i++) A[i] = 0.0;
    for (i = 0; i < N; i++) {
        A[i + i * N] = 2.0;                        /* column-major */
        if (i > 0)     A[i + (i - 1) * N] = -1.0;
        if (i < N - 1) A[i + (i + 1) * N] = -1.0;
    }

    feastinit(fpm);
    fpm[0] = 0;   /* no runtime printing */

    dfeast_syev(&UPLO, &n, A, &lda, fpm, &epsout, &loop,
                &Emin, &Emax, &M0, lambda, q, &mode, res, &info);

    printf("info = %d, loop = %d, epsout = %.3e\n", info, loop, epsout);
    if (info != 0) { printf("FAIL: FEAST returned info=%d\n", info); return 1; }

    printf("found %d eigenvalues in [%g, %g]\n\n", mode, Emin, Emax);
    printf("  k        FEAST            exact            abs err     residual\n");

    double worst = 0.0;
    for (k = 0; k < mode; k++) {
        double exact = 2.0 - 2.0 * cos((k + 1) * M_PI / (N + 1));
        double err = fabs(lambda[k] - exact);
        if (err > worst) worst = err;
        printf("%3d  %16.12f %16.12f   %9.2e   %9.2e\n",
               k + 1, lambda[k], exact, err, res[k]);
    }

    printf("\nmax abs error vs analytic: %.3e\n", worst);
    if (mode != 7)      { printf("FAIL: expected 7 eigenvalues, got %d\n", mode); return 1; }
    if (worst > 1e-10)  { printf("FAIL: accuracy worse than 1e-10\n"); return 1; }

    printf("PASS\n");
    free(lambda); free(q); free(res);
    return 0;
}
