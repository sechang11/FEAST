/* zdotc/cdotc for gfortran against MKL's intel_lp64 interface.
 *
 * FEAST calls ZDOTC and CDOTC as Fortran FUNCTIONS -- 36 sites -- and complex
 * function returns are where the gfortran and Intel Fortran ABIs genuinely
 * disagree: gfortran expects the value in registers (the C99 complex
 * convention), while MKL's intel_lp64 interface writes it through a hidden
 * result pointer. On Linux, Intel ships mkl_gf_lp64 precisely to paper over
 * this; on macOS there is no gf interface at all, so linking gfortran code
 * straight to intel_lp64 makes every ZDOTC call return garbage and misalign
 * the stack.
 *
 * The fix: define zdotc_/cdotc_ ourselves, in C, whose complex return ABI
 * matches gfortran's by construction, and compute through MKL's CBLAS
 * ?dotc_sub -- which returns through an explicit pointer and is therefore
 * immune to the convention split. Link this object anywhere before the MKL
 * libraries and every Fortran call resolves here.
 *
 * FEAST and SPIKE use no other complex-returning BLAS function (grep: no
 * zdotu/cdotu anywhere), so these two cover the whole stack.
 */
#include <complex.h>

/* MKL's CBLAS entry points; declared by hand so no MKL headers are needed at
 * compile time. lp64: 32-bit integers, matching FEAST throughout. */
extern void cblas_zdotc_sub(const int n, const void *x, const int incx,
                            const void *y, const int incy, void *result);
extern void cblas_cdotc_sub(const int n, const void *x, const int incx,
                            const void *y, const int incy, void *result);

double complex zdotc_(const int *n, const void *zx, const int *incx,
                      const void *zy, const int *incy)
{
    double complex r = 0.0;
    cblas_zdotc_sub(*n, zx, *incx, zy, *incy, &r);
    return r;
}

float complex cdotc_(const int *n, const void *cx, const int *incx,
                     const void *cy, const int *incy)
{
    float complex r = 0.0f;
    cblas_cdotc_sub(*n, cx, *incx, cy, *incy, &r);
    return r;
}
