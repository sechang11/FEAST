###########################################################################
#  PATHs to Compilers and libraries
############################################################################ 

############################################################################
########## Select C compiler, OpenMP and flags (needed for C)
#############################################################################
### Default
CC     = gcc 
CFLAGS = -O3 -I${MKLROOT}/include -fopenmp -w 


#############################################################################
########## Select F90 compiler, OpenMP and flags (needed for Fortran)
############################################################################
### Default
FORT  =  ifort  
FFLAGS = -O3 -qopenmp -cpp -i4 -I$(MKLROOT)/include

### other possibility (example)

#FORT  =  gfortran  
#FFLAGS  = -ffree-line-length-none -O3 -I$(MKLROOT)/include -w -fopenmp -fPIC 

########################################################################################################
####### Select PATH to SPIKE Library 
#######################################################################################################

#==============================================
# Specify PATH to SPIKE (main directory)- can be defined as shell variable
#==============================================
ARCH?=x64
SPIKEROOT?=$(PWD)/../..

LOCLIBS=-L$(SPIKEROOT)/lib/$(ARCH)

SPIKE=-lspike

###############################################################  
######## Select PATH to INCLUDE SPIKE files (for C)
##############################################################
INCL=-I$(SPIKEROOT)/include

#################################################################################################
$######## Select libraries 
#########                    LAPACK (mandatory) 
#########                    BLAS (mandatory)
######### Remark: Intel MKL includes Lapack and Blas
#################################################################################################

########### Default (using Intel- MKL for all)

INTELROOT?=/opt/intel
MKLROOT?=${INTELROOT}/composerxe/linux/mkl

############# Fortran examples with Intel Fortran (select one option)

#(i) spike compiled with ifort (option 1) or spike compiled without dependency (option 2)
FLIBS=-mkl
#(ii) spike compiled with gfortran (option 1)
#FLIBS=-Wl,--start-group -lmkl_intel_lp64 -lmkl_gnu_thread -lmkl_core -Wl,--end-group -limf -lpthread -lgfortran


############# Fortran examples with gfortran (select one option)

#(i) spike compiled without fortran runtime dependency (option 2)
#FLIBS = -Wl,--start-group ${MKLROOT}/lib/intel64/libmkl_gf_lp64.a ${MKLROOT}/lib/intel64/libmkl_intel_thread.a ${MKLROOT}/lib/intel64/libmkl_core.a -Wl,--end-group -liomp5 -lpthread -limf -lirc -lm -ldl 
#(ii) spike compiled with gfortran (option 1) and openmp from gnu
#FLIBS = -Wl,--start-group ${MKLROOT}/lib/intel64/libmkl_gf_lp64.a ${MKLROOT}/lib/intel64/libmkl_gnu_thread.a ${MKLROOT}/lib/intel64/libmkl_core.a -Wl,--end-group -lgomp -lpthread -limf -lirc -lm -ldl 
#(iii) spike compiled with ifort (option 1) and qopenmp flag from intel
#FLIBS = -Wl,--start-group ${MKLROOT}/lib/intel64/libmkl_gf_lp64.a ${MKLROOT}/lib/intel64/libmkl_intel_thread.a ${MKLROOT}/lib/intel64/libmkl_core.a -Wl,--end-group -liomp5 -lpthread -lm -ldl -lirc -lifcore -lifcoremt


############ C examples with gcc (select one option)


#(i) spike compiled without fortran runtime dependency (option 2)
CLIBS=-Wl,--start-group -lmkl_intel_lp64 -lmkl_intel_thread -lmkl_core -Wl,--end-group -limf -lsvml -liomp5 -lpthread -lm -lirc 
#(ii) spike compiled with ifort (option 1) 
#CLIBS=-Wl,--start-group -lmkl_intel_lp64 -lmkl_intel_thread -lmkl_core -Wl,--end-group -limf -lsvml -liomp5 -lpthread -lm -lirc -lifcore -lifcoremt
#(iii) spike compiled with gfortran (option 1)
#CLIBS=-Wl,--start-group -lmkl_intel_lp64 -lmkl_gnu_thread -lmkl_core -Wl,--end-group -limf -lpthread -lgfortran
