!!!!!!!!!!!!!!!!
! This file contains a set of examples for pivoting SPIKE with split factorization and solve. 
! Examples begin around line 65.
!!!!!!!!!!!!!!!!!

program main

implicit none
double precision :: a2
integer :: example_number
integer :: n,kl,ku,klu,i,j,lda,ldoA,nrhs,info,ldb
double precision, dimension(:),   allocatable :: norm
double precision, dimension(:),   allocatable :: work
double precision, dimension(:,:), allocatable :: A,B,oA,oB
integer, dimension(:), allocatable :: ipiv
integer, dimension(64) :: spm
character(len=100) :: format
integer :: t0,t1,t2,tim
double precision:: res
double precision, parameter :: d_one=1.0d0
integer,external :: omp_get_num_threads

!!!!!!!!!
! Set up the matrix used for the example.
! For simplicity sake we'll just use a random matrix with some 
! extra weight on the diagonal.
!!!!!!!!!

! Describe the matrices
n    = 128000 ! Matrix width and height
ku   = 60     ! Upper band size
kl   = 60     ! Lower band size
a2   = 1.0d0  ! Degree of diagonal dominance (1.0 for a diagonally dominant matrix)
nrhs = 40     ! Number of right hand sides

! Describe their size in memory
klu  = max(kl,ku)
ldoA = kl+ku+1
lda  = klu+kl+ku+1
ldb  = n

! Allocate space for the matrices (A,B) and space to store
! copies of them to help us calculate the residual at the end
allocate(oA(ldoa,n))
allocate(A(lda,n))
allocate(oB(ldb,nrhs))    
allocate(B(ldb,nrhs))

! Generate the matrix and the right hand sides
call example_matrix_gen(oA,B,a2,n,kl,ku,nrhs,ldb,ldoa) 

! Save copies so we can calculate the residual
oB=B   
A(1+klu:lda,:)=oA   

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
!SPM setting list relevant to gbtrfp/gbtrsp:
! 1  = print flag 1 for timing and partition information, 0 for no printing (except errors). Defaults to 0.
! 2  = spikeinit optimize flag. 0: Use user defined ratios. 1: Set tuning parameters to large NRHS. Defaults to 0.
! 4  = 10 times ratio large. Defaults to 22 (So ratio is 2.2)
! 5  = 10 times ratio small. Defaults to 35 (Ratio 3.5)
! 10 = number of klu*klu blocks required for work array
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

print *, "Pivoting operation with gbtrfp/gbtrsp"
! Initialize spm array to contain default parameters for SPIKE
call spikeinit(spm,n,max(kl,ku))

! Instructs SPIKE to print timing and partition information
spm(1) = 1 

! This work array will hold the reduced system and some other intermediary values.
! The size is dependent on the number of partitions used by SPIKE, but spikeinit will calculate the size automtically. 
allocate(work(klu*klu*spm(10)))
allocate(ipiv(n))
call system_clock(t0,tim)
! Perform the SPIKE factorization
call dspike_gbtrfp(spm,n,kl,ku,A,lda,work,ipiv,info)
call system_clock(t1,tim)
! Perform the solve 
call dspike_gbtrsp(spm,n,kl,ku,nrhs,A,lda,work,ipiv,B,ldb)
call system_clock(t2,tim)
deallocate(work)
deallocate(ipiv)


!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
! End of the example section. 
! Check the residual and print the outcome. 
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

allocate(norm(1:nrhs))
j = 0
res = 0.0d0
do i=1,nrhs
  norm(i)=maxval(abs(oB(1:n,i)))
  call DGBMV('N',N, N, KL, KU, -d_one, oA, ldoa, B(1,i),1,d_one, oB(1,i), 1)
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
