! Check DZGEMM/SCGEMM against a reference built from standard complex BLAS.
!
! The reference promotes the real matrix A to complex and calls ZGEMM, which is
! the operation these shims are meant to reproduce. Any disagreement means the
! shim is wrong, and a wrong shim would corrupt eigenvectors silently.
program test_blas_compat
  implicit none
  integer, parameter :: dp = kind(1.0d0)
  integer :: nfail
  nfail = 0

  call check('N','N', 4, 3, 5, nfail)
  call check('N','T', 4, 3, 5, nfail)
  call check('N','C', 4, 3, 5, nfail)
  call check('T','N', 4, 3, 5, nfail)
  call check('T','T', 4, 3, 5, nfail)
  call check('T','C', 4, 3, 5, nfail)
  call check('C','N', 4, 3, 5, nfail)
  call check('C','C', 4, 3, 5, nfail)
  call check('N','N', 1, 7, 6, nfail)      ! m=1, the shape SPIKE actually uses
  call check('T','N', 1, 7, 6, nfail)
  call check('N','N', 9, 1, 1, nfail)

  if (nfail == 0) then
     print *, 'ALL PASS'
  else
     print *, 'FAILURES:', nfail
     stop 1
  end if

contains

  subroutine check(ta, tb, m, n, k, nfail)
    character, intent(in) :: ta, tb
    integer, intent(in)   :: m, n, k
    integer, intent(inout):: nfail

    double precision, allocatable :: A(:,:)
    complex(dp), allocatable :: B(:,:), C1(:,:), C2(:,:), AC(:,:)
    complex(dp) :: alpha, beta
    integer :: ra, ca, rb, cb, i, j, lda, ldb
    double precision :: err, denom

    if (ta == 'N') then
       ra = m; ca = k
    else
       ra = k; ca = m
    end if
    if (tb == 'N') then
       rb = k; cb = n
    else
       rb = n; cb = k
    end if

    allocate(A(ra,ca), AC(ra,ca), B(rb,cb), C1(m,n), C2(m,n))
    call random_number(A)
    do j = 1, cb
       do i = 1, rb
          B(i,j) = dcmplx(dble(i)*0.3d0 - dble(j)*0.7d0, dble(i+j)*0.11d0 - 0.4d0)
       end do
    end do
    do j = 1, n
       do i = 1, m
          C1(i,j) = dcmplx(0.25d0*i - 0.1d0*j, 0.05d0*(i-j))
       end do
    end do
    C2 = C1
    AC = dcmplx(A, 0.0d0)
    alpha = dcmplx(1.7d0, -0.6d0)
    beta  = dcmplx(-0.4d0, 0.9d0)
    lda = max(1, ra)
    ldb = max(1, rb)

    ! Reference: promote A to complex, use standard ZGEMM.
    call ZGEMM(ta, tb, m, n, k, alpha, AC, lda, B, ldb, beta, C1, max(1,m))
    ! The shim under test.
    call DZGEMM(ta, tb, m, n, k, alpha, A, lda, B, ldb, beta, C2, max(1,m))

    err = maxval(abs(C1 - C2))
    denom = max(1.0d0, maxval(abs(C1)))
    if (err / denom > 1.0d-12) then
       print '(A,A1,A1,A,3I4,A,ES10.2)', '  FAIL ', ta, tb, ' m,n,k=', m, n, k, ' err=', err
       nfail = nfail + 1
    else
       print '(A,A1,A1,A,3I4,A,ES10.2)', '  pass ', ta, tb, ' m,n,k=', m, n, k, ' err=', err
    end if
    deallocate(A, AC, B, C1, C2)
  end subroutine check

end program test_blas_compat
