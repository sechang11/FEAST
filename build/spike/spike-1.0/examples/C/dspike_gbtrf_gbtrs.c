#include <stdio.h> 
#include <stdlib.h> 
#include <sys/time.h>
#include <math.h>
#include <omp.h>
#include "spike.h"

// A set of examples showing the use of dspike_gbsv

// Define macro to allow easier matrix manipulation in the proper FORTRAN manner (Column major).
// NB, the leading dimension of each matrix must be defined as ld<matrix pointer name> to use this (It is a concatenation macro).
#define M(p,j,i) p[j+ ld##p *(i)]
enum bool {false,true};

// Helper function to generate the example matrix
void example_matrix_gen(double *A, double* B, double DD, int n, int kl, int ku, int nrhs, int ldA, int ldB);

int main() {
	/* Spike variables declaration */
	int	spikeparam[64]; 
	char trans;

	/* Matrix variables declaration */
	double *A,*oA;
	double *work;
	double *res;
	double res_max;
	double *B,*oB;
	int i_one=1;
	double d_one  = 1.0;
	double d_mone =-1.0;
	int example_number,n,kl,ku,klu,ldB,ldA,ldoA,ldoB,nrhs;
	double DD;
	/* Others */
	int	i,j;
	int	info;
	double t1,t2,t3;

	n  = 128000; // Matrix width and height
	ku = 60;     // Upper band size
	kl = 60;     // Lowe band size
	DD = 1.0;    // Degreee of diagonal dominance (1.0 for diagonally dominant matrix). Decrease this to around .1 if you want to see iterative refinement work.  
	nrhs = 40;   // Number of right hand sides 

	klu  = kl*(kl>ku) + ku*(ku>=kl) ;
	ldA  = kl+ku+1;
	ldoA = kl+ku+1;
	ldB  = n; 
	ldoB = n; 

	A  = malloc(n*ldA*sizeof(double));
	oA = malloc(n*ldoA*sizeof(double));
	B  = malloc(ldB*nrhs*sizeof(double));
	oB = malloc(ldoB*nrhs*sizeof(double));
	res = malloc(nrhs*sizeof(double));

	// Generate the example matrix and set the requested degree of diagonal dominance.
	example_matrix_gen(A, B, DD, n, kl, ku, nrhs, ldA, ldB);

	// Finally, copy these matrices into the copy matrices.
	for(j=0;j<ldA;j++)
	{
		for(i=0;i<n;i++)
			M(oA,j,i) = M(A,j,i);
	}


	for(j=0;j<ldB;j++)
	{
		for(i=0;i<nrhs;i++)
			M(oB,j,i) = M(B,j,i);
	}

	//==============================================
	//The matrices are setup, start the SPIKE stuff.
	//==============================================
	/*
	SPM settings relevant to dspike_gbsv:
	0  = print flag. 1: timing and partition information, 0: no printing (except errors, naturally). Default 0.
	1  = spikeinit optimize flag. 0: Use user defined ratios. 1: Set tuning parameters to large NRHS. 2: DSPIKE_GBSV use compromise tuning ratios based on spm(7)
	2  = Pivoting/Iterative refinement flag. 0: neither, 1: iterative refinement, 2: pivoting 
	3  = 10 times ratio large. Defaults to 22 (So ratio is 2.2)
	4  = 10 times ratio small. Defaults to 35 (Ratio 3.5)
	10 = max number of iterations for iterative solve
	11 = exponent for residual tolerance -- I.E, res tolerance is 10^-spm(12)
	13 = The type of norm to use for calculations of residual in the iterative refinement -- 0 for infinorm, 1 for norm1, 2 for norm2
	*/


	example_number = 0;


	
	// Minimal user work with factorize and solve stage.
	// Optionally this may be used for a transpose problem.
	// This example uses all default settings, except for printing (turned on for example sake) 
	if(example_number == 0)
	{
		// Initalize the spike params array 
		spikeinit(spikeparam,&n,&klu);
		// Instruct SPIKE to print iming and partitioning info
		spikeparam[0] = 1;
		
		// The work array will hold the reduced system and some other values
		// The size is dependent on the number of paritions, but spikeinit will calculate it for us
		work  = malloc(klu*klu*spikeparam[9]*sizeof(double));
		// Let's do a transpose problem here. 
		trans = 'n';
		t1=omp_get_wtime();
		dspike_gbtrf(spikeparam,&n,&kl,&ku,A,&ldA,work,&info);
		t2=omp_get_wtime();
		dspike_gbtrs(spikeparam,&trans,&n,&kl,&ku,&nrhs,A,&ldA,work,B,&ldB);
		t3=omp_get_wtime();
	}

	// Similar to previous example, but this uses the solver with iterative refinement
	// It requires an unmodified copy of the A matrix to perform the refinement. 
	// The copy of the matrix is unmodified on exit, so we can use oA here.
	if(example_number == 1)
	{
		// Initalize the spike params array 
		spikeinit(spikeparam,&n,&klu);
		// Instruct SPIKE to print iming and partitioning info
		spikeparam[0] = 1;
		// Set partition sized to many-right-hand sides
		spikeparam[1] = 1;
		// Set up the iterative refinement thresholds
		spikeparam[10] = 3;
		spikeparam[11] = 12;

		// The work array will hold the reduced system and some other values
		// The size is dependent on the number of paritions, but spikeinit will calculate it for us
		work  = malloc(klu*klu*spikeparam[9]*sizeof(double));
		// Let's do a transpose problem here. 
		trans = 't';
		t1=omp_get_wtime();
		dspike_gbtrf(spikeparam,&n,&kl,&ku,A,&ldA,work,&info);
		t2=omp_get_wtime();
		DSPIKE_GBTRSI(spikeparam,&trans,&n,&kl,&ku,&nrhs,oA,&ldA,A,&ldA,work,B,&ldB);
		t3=omp_get_wtime();
	}

//==============================================
//SPIKE is done, calculate the residuals
//==============================================

	for(i=0;i<nrhs;i++)
	{
		res[i] = M(oB,idamax(&n,&M(oB,0,i),&i_one)-1,i);
	}

	// Get the relative residual; 
	
	for(i=0;i<nrhs;i++)
	{
		DGBMV(&trans, &n, &n, &kl, &ku, &d_mone, oA, &ldA, &M(B,0,i),&i_one,&d_one, &M(oB,0,i), &i_one);
		res[i] = M(oB,idamax(&n,&M(oB,0,i),&i_one)-1,i)/res[i];
	}


	res_max=0.0;
	for(i=0;i<nrhs;i++)
	{
		if(fabs(res[i]) >= res_max) res_max = fabs(res[i]);
	}
	printf("n, \t kl, \t ku, \t nrhs, \t residual, \t time fac, \t time sol, \t time all\n");
	printf("%.2E, \t %d, \t %d, \t %d, \t %.3E, \t %.3E, \t %.3E, \t %.3E \n",(float) n,kl,ku,nrhs,res_max,t2-t1,t3-t2,t3-t1);

	free(A);
	free(oA);
	free(B);
	free(oB);

	return 0;
}


void example_matrix_gen(double *A, double* B, double DD, int n, int kl, int ku, int nrhs, int ldA, int ldB)
{
	int iseed[4];
	int two=2;
	int ldan,ldbnrhs;  // Dealing with c->fortran function weirdness.
	int i,j;
	double sumA;
	int sign;

	//Set the iseed array. It is part of the DLARNV definition. The fourth value must be an odd number so I've hardcoded it to 33. 
	iseed[0] = 1000;
	iseed[1] = 1000;
	iseed[2] = 1000;
	iseed[3] = 33;


	//Fill A up with random doubles.
	ldan=ldA*n; 
	ldbnrhs=ldB*nrhs;

	DLARNV(&two,iseed,&ldan,A);
	DLARNV(&two,iseed,&ldbnrhs,B);

	//The top-leftmost and bottom-rightmost elements of this array are not actually part of the matrix (see lapack banded storage documentation) 
	//So, we'll zero them out here, so they don't get included in the magnitude calculation for each column (if we don't the matrix will have an unfairly high degree of diagonal dominance and SPIKE will look better than it really is)

	for(i=0; i<ku; i++)
		for(j=0; j<ku-i; j++)
		{
			M(A,j,i) = 0.0;

		}

	for(i=0; i<kl; i++)
		for(j=kl; j>i; j--)
		{
			M(A,ku+j,n-(i+1)) = 0.0;

		}


	//Set up the desired degree of diagonal dominance	
	for(i=0;i<n;i++)
	{
		//Sum up the column magnitude except for the middle
		//Needed to use fabs because it is fouble precision.
		sumA=0.0;
		for(j=0;j<ku;j++)
			sumA=sumA+fabs(M(A,j,i));

		for(j=ku+1;j<ldA;j++)
			sumA=sumA+fabs(M(A,j,i));

		//Diagonal dominance doesn't actually care about the sign of the diagonal.
		//I've decided to keep the sign that dlarnv gave us.
		sign = (M(A,ku,i) > 0) - (M(A,ku,i) < 0);

		//Multiply by DD to set the diagonal dominance.
		M(A,ku,i) = sign*sumA*DD;

	}



}




