
!!!!!!!!!!!!!!!!
!
! This file contains a set of examples for SPIKE. 
! Examples begin around line 100.
!
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
integer :: t0,t1,t2,tim
double precision:: res
character :: trans
double precision, parameter :: d_one=1.0d0
integer,external :: omp_get_num_threads

!!!!!!!!!
!
! Set up the matrix used for the example.
! For simplicity sake we'll just use a random matrix with some 
! extra weight on the diagonal.
!
!!!!!!!!!

! Describe the matrices
n    = 128000 ! Matrix width and height
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
!   Example 0 a split factorization and solve
!   Example 1 a split factorization and solve, with iterative refinement enabled for the solve 
example_number = 0
!example_number = 1

! Set up the variables for the computation. 
! Note that not all of these options make sense for every example --
! for example, dspike_gbsv doesn't allow a transpose option. 
trans   = 't'  ! Is this a transpose problem? N for non-transpose, T for transpose
maxiter = 3    ! If iterative refinement will be used, this is the maximum number of iterations allowed
restol  = 12   ! If iterative refinement will be used, this is the negative exponent (base 10) of the tolerance. So, with restol=13
               ! means we'll allow 10^-13 as the maximum residual. 
normtype= 0    ! Indicates the type of norm to use inside SPIKE (for example, for iterative refinement residual calculation) 
               ! 0=infinorm 1=norm1 2=norm2 

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

!SPM setting list:
! 1  = print flag 1 for timing information, 2 for partition information, 0 for no printing (except errors, naturally), 3 for both
! 2  = spikeinit optimize flag. 0: Use user defined ratios. 1: Set tuning parameters to large NRHS.
! 4  = 10 times ratio large. Defaults to 22 (So ratio is 2.2)
! 5  = 10 times ratio small. Defaults to 35 (Ratio 3.5)
! 10 = number of klu*klu blocks required for work array
! 11 = max number of iterations for iterative solve
! 12 = exponent for residual tolerance -- I.E, res tolerance is 10^-spm(12)
! 14 = The type of norm to use for calculations of residual in the iterative refinement -- 0 for infinorm, 1 for norm1, 2 for norm2

! Minimal user work with factorize and solve stage.
! Optionally this may be used for a transpose problem.
! Note that this example does not perform iterative refinement (see next example refinement)
if(example_number .eq. 0) then
  print *, "Split solve and factorize, no refinement"
  ! Initialize spm array to contain default parameters for SPIKE
  call spikeinit(spm,n,max(kl,ku))

  ! Instructs SPIKE to print timing and partition information
  spm(1) = 1 

  ! This work array will hold the reduced system and some other intermediary values.
  ! The size is dependent on the number of partitions used by SPIKE, but spikeinit will calculate the size automatically. 
  allocate(work(klu*klu*spm(10)))
  
  call system_clock(t0,tim)
  call dspike_gbtrf(spm,n,kl,ku,A,lda,work,info)
  call system_clock(t1,tim)
  call dspike_gbtrs(spm,trans,n,kl,ku,nrhs,A,lda,work,B,ldb)
  call system_clock(t2,tim)
  deallocate(work)

endif

! Similar to previous example, but this uses the solver with iterative refinement
! It requires an unmodified copy of the A matrix to perform the refinement. 
! The copy of the matrix is unmodified on exit, so we can use oA here.
if(example_number .eq. 1) then
  print *, "Split solve and factorize, with refinement"
  ! Initialize spm array to contain default parameters for SPIKE
  call spikeinit(spm,n,max(kl,ku))
  ! Instructs SPIKE to print timing and partition information
  spm(1) = 1 
  ! Set the partition sizes to favor many solve operations, because iterative refinement might involve extra solves.
  spm(2) = 1
  ! Use the previously set values for iterative refinement 
  spm(11) = maxiter
  spm(12) = restol 
  spm(14) = normtype

  ! This work array will hold the reduced system and some other intermediary values.
  ! The size is dependent on the number of partitions used by SPIKE, but spikeinit will calculate the size automtically. 
  allocate(work(klu*klu*spm(10)))

  call system_clock(t0,tim)
  oA=A  ! Perform copy of A again so that the timing is accurately represented.
  call dspike_gbtrf(spm,n,kl,ku,A,lda,work,ipiv,info)
  call system_clock(t1,tim)
  call dspike_gbtrsi(spm,trans,n,kl,ku,nrhs,oA,lda,A,lda,work,B,ldb)
  call system_clock(t2,tim)
  deallocate(work)
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
  call DGBMV(trans, N, N, KL, KU, -d_one, oA, lda, B(1,i),1,d_one, oB(1,i), 1)
  if(maxval(abs(oB(1:n,i)))/norm(i) > abs(res)) then 
    res = maxval(abs(oB(1:n,i)))/norm(i)
    j = i
  endif
enddo

format = '(A69)'
write (*,format) '       n   kl   ku  nrhs          resid    t_fact   t_solve    t_both' 
format = '(I8, I5, I5, I6, E15.4, E10.3, E10.3, E10.3)'
write (*,format) n,kl,ku,nrhs,abs(res),(t1-t0)*1.0d0/(tim*1.0d0),(t2-t1)*1.0d0/(tim*1.0d0),(t2-t0)*1.0d0/(tim*1.0d0)

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
