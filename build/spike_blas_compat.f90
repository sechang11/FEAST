! DZGEMM and SCGEMM -- mixed real-by-complex matrix products.
!
! SPIKE's banded routines call these for the case "A is real, B and C are
! complex". They are Intel MKL extensions, not standard BLAS, so a build
! against OpenBLAS (or Apple's Accelerate) fails to link with
! "undefined reference to dzgemm_". SPIKE's own source says as much:
!
!   DZGBMM :: Same than ZGBMM but A matrix is real --> works only with
!             DZGEMM (MKL-BLAS)
!
! The operation decomposes exactly into two real products, so nothing is
! approximated here:
!
!   op(A) * op(B) = op(A)*Re(op(B))  +  i * op(A)*Im(op(B))
!
! Link this alongside SPIKE when *not* building against MKL. With MKL, leave it
! out and use Intel's implementation, which is faster.

subroutine DZGEMM(TRANSA, TRANSB, M, N, K, ALPHA, A, LDA, B, LDB, BETA, C, LDC)
  implicit none
  character          :: TRANSA, TRANSB
  integer            :: M, N, K, LDA, LDB, LDC
  complex(kind=8)    :: ALPHA, BETA
  double precision   :: A(LDA,*)
  complex(kind=8)    :: B(LDB,*), C(LDC,*)

  double precision, allocatable :: BR(:,:), BI(:,:), TR(:,:), TI(:,:)
  integer          :: rb, cb, i, j, ldbr
  character        :: ta, tb
  double precision :: sgn
  double precision, parameter :: ONE = 1.0d0, ZERO = 0.0d0

  if (M <= 0 .or. N <= 0) return

  ! A is real, so a conjugate transpose is just a transpose.
  ta = TRANSA
  if (ta == 'C' .or. ta == 'c') ta = 'T'

  ! For B, 'C' means transpose *and* negate the imaginary part. Handling the
  ! negation here lets both real products use a plain transpose.
  tb  = TRANSB
  sgn = ONE
  if (tb == 'C' .or. tb == 'c') then
     tb  = 'T'
     sgn = -ONE
  end if

  ! Shape of B as stored, which depends on whether it is transposed in use.
  if (TRANSB == 'N' .or. TRANSB == 'n') then
     rb = K; cb = N
  else
     rb = N; cb = K
  end if

  allocate(BR(rb,cb), BI(rb,cb), TR(M,N), TI(M,N))
  do j = 1, cb
     do i = 1, rb
        BR(i,j) = dble(B(i,j))
        BI(i,j) = sgn * dimag(B(i,j))
     end do
  end do
  ldbr = max(1, rb)

  call DGEMM(ta, tb, M, N, K, ONE, A, LDA, BR, ldbr, ZERO, TR, max(1,M))
  call DGEMM(ta, tb, M, N, K, ONE, A, LDA, BI, ldbr, ZERO, TI, max(1,M))

  do j = 1, N
     do i = 1, M
        C(i,j) = ALPHA * dcmplx(TR(i,j), TI(i,j)) + BETA * C(i,j)
     end do
  end do

  deallocate(BR, BI, TR, TI)
end subroutine DZGEMM


subroutine SCGEMM(TRANSA, TRANSB, M, N, K, ALPHA, A, LDA, B, LDB, BETA, C, LDC)
  implicit none
  character       :: TRANSA, TRANSB
  integer         :: M, N, K, LDA, LDB, LDC
  complex(kind=4) :: ALPHA, BETA
  real(kind=4)    :: A(LDA,*)
  complex(kind=4) :: B(LDB,*), C(LDC,*)

  real(kind=4), allocatable :: BR(:,:), BI(:,:), TR(:,:), TI(:,:)
  integer      :: rb, cb, i, j, ldbr
  character    :: ta, tb
  real(kind=4) :: sgn
  real(kind=4), parameter :: ONE = 1.0e0, ZERO = 0.0e0

  if (M <= 0 .or. N <= 0) return

  ta = TRANSA
  if (ta == 'C' .or. ta == 'c') ta = 'T'

  tb  = TRANSB
  sgn = ONE
  if (tb == 'C' .or. tb == 'c') then
     tb  = 'T'
     sgn = -ONE
  end if

  if (TRANSB == 'N' .or. TRANSB == 'n') then
     rb = K; cb = N
  else
     rb = N; cb = K
  end if

  allocate(BR(rb,cb), BI(rb,cb), TR(M,N), TI(M,N))
  do j = 1, cb
     do i = 1, rb
        BR(i,j) = real(B(i,j))
        BI(i,j) = sgn * aimag(B(i,j))
     end do
  end do
  ldbr = max(1, rb)

  call SGEMM(ta, tb, M, N, K, ONE, A, LDA, BR, ldbr, ZERO, TR, max(1,M))
  call SGEMM(ta, tb, M, N, K, ONE, A, LDA, BI, ldbr, ZERO, TI, max(1,M))

  do j = 1, N
     do i = 1, M
        C(i,j) = ALPHA * cmplx(TR(i,j), TI(i,j)) + BETA * C(i,j)
     end do
  end do

  deallocate(BR, BI, TR, TI)
end subroutine SCGEMM
