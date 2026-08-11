!!!!!!!!!!!!!!!!
! This file contains a set of examples for the SPIKE gbsv function. 
! Examples begin around line 100.
!!!!!!!!!!!!!!!!!
 
program main

implicit none
double precision :: a2
integer :: example_number
integer :: n,kl,ku,klu,i,j,lda,nrhs,info,ldb
double precision, dimension(:),   allocatable :: norm
double precision, dimension(:),   allocatable :: work
double precision, dimension(:,:), allocatable :: A,B,oA,oB
integer, dimension(:), allocatable :: ipiv
integer, dimension(64) :: spm
character(len=100) :: format
integer :: maxiter, restol, normtype
integer :: t0,t1,tim
double precision:: res
double precision, parameter :: d_one=1.0d0
integer,external :: omp_get_num_threads

!!!!!!!!!
! Set up the matrix used for the example.
! For simplicity sake we'll just use a random matrix with some 
! extra weight on the diagonal.
!!!!!!!!!

! Describe the matrices
n    = 1280000  ! Matrix width and height
ku   = 60     ! Upper band size
kl   = 60     ! Lower band size
a2   = 1.0d0  ! Degree of diagonal dominance (1.0d0 for a diagonally dominant matrix)
nrhs = 40     ! Number of right hand sides

! Describe their size in memory
klu  = max(kl,ku)
lda  = kl+ku+1
ldb  = n

! Allocate space for the matrices (A,B) and space to store
! copies of them to help us calculate the residual at the end
allocate(oA(lda,n))
allocate(A(lda,n))
allocate(oB(ldb,nrhs))    
allocate(B(ldb,nrhs))

! Generate the matrix and the right hand sides
call example_matrix_gen(A,B,a2,n,kl,ku,nrhs,ldb,lda) 

! Save copies so we can calculate the residual
oB=B   
oA=A

! Select the example you would like to use.
!   Example 0 uses non-pivoting operation
!   Example 1 uses non-pivoting operation with iterative refinement
!   Example 2 uses pivoting operation
example_number = 0
!example_number = 1
!example_number = 2

! Set up the variables for the computation. 
maxiter = 3    ! If iterative refinement will be used, this is the maximum number of iterations allowed
restol  = 12   ! If iterative refinement will be used, this is the negative exponent (base 10) of the tolerance. So, with restol=13
               ! means we'll allow 10^-13 as the maximum residual. 
normtype= 0    ! Indicates the type of norm to use inside SPIKE (for example, for iterative refinement residual calculation) 
               ! 0=infinorm 1=norm1 2=norm2 

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

!SPM settings relevant to dspike_gbsv:
! 1  = print flag. 1: timing and partition information, 0: no printing (except errors, naturally). Default 0.
! 2  = spikeinit optimize flag. 0: Use user defined ratios. 1: Set tuning parameters to large NRHS. 2: DSPIKE_GBSV use compromise tuning ratios based on spm(7)
! 3  = Pivoting/Iterative refinement flag. 0: neither, 1: iterative refinement, 2: pivoting 
! 4  = 10 times ratio large. Defaults to 22 (So ratio is 2.2)
! 5  = 10 times ratio small. Defaults to 35 (Ratio 3.5)
! 7  = 10 times constant K -- tuning constant for system 
! 11 = max number of iterations for iterative solve
! 12 = exponent for residual tolerance -- I.E, res tolerance is 10^-spm(12)
! 14 = The type of norm to use for calculations of residual in the iterative refinement -- 0 for infinorm, 1 for norm1, 2 for norm2

! This is the basic example for the combined factorize and solve subroutine. 
! This example uses all default settings, except for printing (turned on for example sake) 
if(example_number .eq. 0) then
  print *, "Basic gbsv example, no precision improvement"
  ! Initialize spm array to contain default parameters for SPIKE
  call spikeinit(spm,n,max(kl,ku))
  ! Instructs SPIKE to print timing and partition information
  spm(1) = 1 

  call system_clock(t0,tim)
  ! The actual function call
  call dspike_gbsv(spm,n,kl,ku,nrhs,A,lda,B,ldb,info)
  call system_clock(t1,tim)

endif


! Combined factorize and solve, but with custom settings and iterative refinement. 
if(example_number .eq. 1) then
  print *, "Customized dspike_gbsv example with iterative refinement"

  ! Initialize spm array to contain default parameters for SPIKE
  call spikeinit(spm,n,max(kl,ku))
  ! Instructs SPIKE to print timing and partition information
  spm(1) = 1 
  ! Set partition sizes to many right-hand-sides
  spm(2) = 1
  ! Use iterative refinement
  spm(3) = 2 

  ! Use the previously set values for iterative refinement
  spm(11) = maxiter
  spm(12) = restol 
  spm(14) = normtype
  
  call system_clock(t0,tim)
  ! The actual function call
  call dspike_gbsv(spm,n,kl,ku,nrhs,A,lda,B,ldb,info)
  call system_clock(t1,tim)

endif

! Combined factorize and solve, but with custom settings and partial pivoting operation and a manually set number of threads. 
if(example_number .eq. 2) then
  print *, "Customized dspike_gbsv example with partial pivoting"

  ! Initialize spm array to contain default parameters for SPIKE
  call spikeinit_nthread(spm,n,max(kl,ku),2)
  ! Instructs SPIKE to print timing and partition information
  spm(1) = 1 
  ! Set partition sizes to many compromise between solve and factorize stages
  spm(2) = 2
  ! Use pivoting solve 
  spm(3) = 1 

  call dspike_tune(spm)
  
  call system_clock(t0,tim)
  ! The actual function call
  call dspike_gbsv(spm,n,kl,ku,nrhs,A,lda,B,ldb,info)
  call system_clock(t1,tim)

endif

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
! End of the example section. 
! Check the residual and print the outcome. 
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

allocate(norm(1:nrhs))
j = 0
res = 0.0d0
do i=1,nrhs
  norm(i)=maxval(abs(oB(1:n,i)))
  call DGBMV('n', N, N, KL, KU, -d_one, oA, lda, B(1,i),1,d_one, oB(1,i), 1)
  if(maxval(abs(oB(1:n,i)))/norm(i) > abs(res)) then 
    res = maxval(abs(oB(1:n,i)))/norm(i)
    j = i
  endif
enddo


format = '(A49)'
write (*,format) '       n   kl   ku  nrhs          resid      time' 
format = '(I8, I5, I5, I6, E15.4, E10.3)'
write (*,format) n,kl,ku,nrhs,abs(res),(t1-t0)*1.0d0/(tim*1.0d0)

end program

! This subroutine creates a matrix with the desired 'degree of diagonal dominance.'
! That is, A(i,i) = alpha*sum(abs(A(j,i))) j =/= i
subroutine example_matrix_gen(A,B,a2,n,kl,ku,nrhs,ldb,lda) 
implicit none
integer :: i,n,kl,ku,nrhs,lda,ldb,top_adjust, bottom_adjust
double precision :: a1, a2
integer, dimension(4) :: iseed
double precision, dimension(lda,   n) :: A
double precision, dimension(ldb,nrhs) :: B

iseed(4) = 33
iseed(1:3) = 1000

call DLARNV(2,iseed,lda*n,A)
call DLARNV(2,iseed,ldb*nrhs,B)

do i=1,n
  if( (i .gt. 1) .and. (i .lt. n) ) then
    top_adjust = min(i-1,ku)
    bottom_adjust = min(kl,n-i)
    a1 = sum(abs(A(1+ku-top_adjust:ku,i))) + sum(abs(A(ku+2:lda+bottom_adjust-kl,i)))
  endif

  if( ( i .eq. 1) ) then
    a1 = sum(abs(A(ku+2:lda,i)))
  endif

  if( ( i .eq. n) ) then
    a1 = sum(abs(A(1:ku,i)))
  endif

  A(ku+1,i) = (A(ku+1,i)/abs(A(ku+1,i)))*a1*a2
enddo

end subroutine
