#include <stdio.h> 
#include <stdlib.h> 
#include <sys/time.h>
#include <math.h>
#include <omp.h>
#include "spike.h"

// A set of examples showing the use of cspike_gbsv

// Define macro to allow easier matrix manipulation in the proper FORTRAN manner (Column major, and with complex numbers).
// NB, the leading dimension of each matrix must be defined as ld<matrix pointer name> to use this (It is a concatenation macro).
#define M(p,j,i) p[2*(j+ ld##p *(i))]
#define Mi(p,j,i) p[2*(j+ ld##p *(i))+1]
enum bool {false,true};

// Helper function to generate the example matrix
void example_matrix_gen(float *A, float* B, float DD, int n, int kl, int ku, int nrhs, int ldA, int ldB);

int main() {
	/* Spike variables declaration */

	int	spikeparam[64]; 

	/* Matrix variables declaration */
	char trans = 'n';
	float *A,*oA;
	float *res;
	float temp[2];
	float res_max;
	float *B,*oB;
	int i_one=1;
	float c_one[2]  =  {1.0,0.0};
	float c_mone[2] = {-1.0,0.0};
	int example_number,n,kl,ku,klu,ldB,ldA,ldoA,ldoB,nrhs,max_index;
	float DD;
	int two = 2;
	int one = 1;
	/* Others */
	int	i,j;
	int	info;
	double t1,t2;
	float realrez;

	n  = 64000; // Matrix width and height
	ku = 60;     // Upper band size
	kl = 60;     // Lowe band size
	DD = 0.15;    // Degreee of diagonal dominance (1.0 for diagonally dominant matrix). Try a value around .1 to see the effects of iterative refinement and pivoting.
	nrhs = 40;   // Number of right hand sides 

	klu  = kl*(kl>ku) + ku*(ku>=kl) ;
	ldA  = kl+ku+1;
	ldoA = kl+ku+1;
	ldB  = n; 
	ldoB = n; 

	A  = malloc(n*ldA*2*sizeof(float));
	oA = malloc(n*ldA*2*sizeof(float));
	B  = malloc(ldB*nrhs*2*sizeof(float));
	oB = malloc(ldB*nrhs*2*sizeof(float));
	res = malloc(nrhs*sizeof(float));

	// Generate the example matrix and set the requested degree of diagonal dominance.
	example_matrix_gen(A, B, DD, n, kl, ku, nrhs, ldA, ldB);

	// Finally, copy these matrices into the copy matrices.
	for(j=0;j<ldA;j++)
	{
		for(i=0;i<n;i++)
		{
			M(oA,j,i)  = M(A,j,i);
			Mi(oA,j,i) = Mi(A,j,i);
		}
	}


	for(j=0;j<ldB;j++)
	{
		for(i=0;i<nrhs;i++)
		{
			M(oB,j,i)  = M(B,j,i);
			Mi(oB,j,i) = Mi(B,j,i);
		}
	}

//==============================================
//The matrices are setup, start the SPIKE stuff.
//==============================================
/*
SPM settings relevant to cspike_gbsv:
0  = print flag. 1: timing and partition information, 0: no printing (except errors, naturally). Default 0.
1  = spikeinit optimize flag. 0: Use user defined ratios. 1: Set tuning parameters to large NRHS. 2: CSPIKE_GBSV use compromise tuning ratios based on spikeparam(6)
2  = Pivoting/Iterative refinement flag. 0: neither, 1: iterative refinement, 2: pivoting 
3  = 10 times ratio large. Defaults to 22 (So ratio is 2.2)
4  = 10 times ratio small. Defaults to 35 (Ratio 3.5)
6  = 10 times constant K -- tuning constant for system 
10 = max number of iterations for iterative solve
12 = exponent for residual tolerance -- I.E, res tolerance is 10^-spikeparam(12)
13 = The type of norm to use for calculations of residual in the iterative refinement -- 0 for infinorm, 1 for norm1, 2 for norm2
*/


	example_number = 1;


	// This is the basic example for the combined factorize and solve subroutine. 
	// This example uses all default settings, except for printing (turned on for example sake) 
	if(example_number == 0)
	{
		// Initalize the spike params array 
		spikeinit(spikeparam,&n,&klu);
		// Instruct SPIKE to print iming and partitioning info
		spikeparam[0] = 1;
		t1=omp_get_wtime();
		cspike_gbsv(spikeparam,&n,&kl,&ku,&nrhs,A,&ldA,B,&ldB,&info);
		t2=omp_get_wtime();
	}

	// Combined factorize and solve, but with custom settings and iterative refinement 
	if(example_number == 1)
	{
		// Initalize the spike params array 
		spikeinit(spikeparam,&n,&klu);
		// Instruct SPIKE to print iming and partitioning info
		spikeparam[0] = 1;
		// Set partition sized to many-right-hand sides
		spikeparam[1] = 1;
		// Use iterative refinement 
		spikeparam[2] = 2;
		// Set up the iterative refinement thresholds
		spikeparam[10] = 3;
		spikeparam[12] = 6;
		spikeparam[13] = 0;

		t1=omp_get_wtime();
		cspike_gbsv(spikeparam,&n,&kl,&ku,&nrhs,A,&ldA,B,&ldB,&info);
		t2=omp_get_wtime();
	}

// Combined factorize and solve, but with partial pivoting and hardcoded number of partitions. 
	if(example_number == 2)
	{
		// Initalize the spike params array with two partitions hardcoded
		spikeinit_nthread(spikeparam,&n,&klu,&two);
		// Instruct SPIKE to print iming and partitioning info
		spikeparam[0] = 1;
		// Set partition sized to many-right-hand sides
		spikeparam[1] = 2;
		// Use iterative refinement 
		spikeparam[2] = 1;

		cspike_tune(spikeparam);

		t1=omp_get_wtime();
		cspike_gbsv(spikeparam,&n,&kl,&ku,&nrhs,A,&ldA,B,&ldB,&info);
		t2=omp_get_wtime();
	}

//==============================================
//SPIKE is done, calculate the residuals
//==============================================

	// Get the relative residual; 
	for(i=0;i<nrhs;i++)
	{
		CGBMV(&trans, &n, &n, &kl, &ku, &c_mone, oA, &ldA, &M(B,0,i),&i_one,&c_one, &M(oB,0,i), &i_one);
		max_index = icamax(&n,&M(oB,0,i),&i_one);
		res[i] = sqrt((M(oB,max_index,i))*(M(oB,max_index,i)) + (Mi(oB,max_index,i))*(Mi(oB,max_index,i)));
	}
	res_max=0.0;
	for(i=0;i<nrhs;i++)
	{
		if(res[i] >= res_max) res_max = res[i];
	}
	printf("n, \t kl, \t ku, \t nrhs, \t residual, \t time\n");
	printf("%.2E, \t %d, \t %d, \t %d, \t %.3E, \t %.3E \n",(float) n,kl,ku,nrhs,res_max,t2-t1);

	free(A);
	free(oA);
	free(B);
	free(oB);

	return 0;
}


void example_matrix_gen(float *A, float* B, float DD, int n, int kl, int ku, int nrhs, int ldA, int ldB)
{
	int iseed[4];
	int two,ldan,ldbnrhs;  // Dealing with c->fortran function weirdness.
	int i,j;
	float sumA;
	int sign;

	//Set the iseed array. It is part of the DLARNV definition. The fourth value must be an odd number so I've hardcoded it to 33. 
	iseed[0] = 1000;
	iseed[1] = 1000;
	iseed[2] = 1000;
	iseed[3] = 33;


	//Fill A up with random floats.
	ldan=ldA*n; 
	two=2;
	ldbnrhs=ldB*nrhs;

	CLARNV(&two,iseed,&ldan,A);
	CLARNV(&two,iseed,&ldbnrhs,B);

	//The top-leftmost and bottom-rightmost elements of this array are not actually part of the matrix (see lapack banded storage documentation) 
	//So, we'll zero them out here, so they don't get included in the magnitude calculation for each column (if we don't the matrix will have an unfairly high degree of diagonal dominance and SPIKE will look better than it really is)

	for(i=0; i<ku; i++)
		for(j=0; j<ku-i; j++)
		{
			M(A,j,i)  = 0.0;
			Mi(A,j,i) = 0.0;
		}

	for(i=0; i<kl; i++)
		for(j=kl; j>i; j--)
		{
			M(A,ku+j,n-(i+1))  = 0.0;
			Mi(A,ku+j,n-(i+1)) = 0.0;
		}


	//Set up the desired degree of diagonal dominance	
	for(i=0;i<n;i++)
	{
		//Sum up the column magnitude except for the middle
		//Needed to use fabs because it is fouble precision.
		sumA=0.0;
		for(j=0;j<ku;j++)
			sumA=sumA+fabs(M(A,j,i))+fabs(Mi(A,j,i));

		for(j=ku+1;j<ldA;j++)
			sumA=sumA+fabs(M(A,j,i))+fabs(Mi(A,j,i));

		//Diagonal dominance doesn't actually care about the sign of the diagonal.
		//I've decided to keep the sign that dlarnv gave us.
		sign = (M(A,ku,i) > 0) - (M(A,ku,i) < 0);

		//Multiply by DD to set the diagonal dominance.
		M(A,ku,i) = sign*sumA*DD/2;
		Mi(A,ku,i) = sign*sumA*DD/2;

	}



}




