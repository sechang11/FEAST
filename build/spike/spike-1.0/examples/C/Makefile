include ../make.inc

help:
	@echo "Usage: make {all clean} "
	@echo "make all    -- compile all examples for this directory "
	@echo "make clean  -- clean all examples for this directory "
	@echo "!!!!Please correct accordingly compiler and libraries paths, change compiler options " 
	@echo " in file ../../make.inc !!!!"
	@echo

ARCH:=none
ifeq ($(ARCH),none)
  ARCH:=x64
endif
#==============================================================
# Include the LIB (spike and  - lapack - blas)  
#==============================================================
LIB = $(LOCLIBS) $(SPIKE) $(CLIBS)

all: normal pivoting double 

normal: dspike_gbsv.exe dspike_gbtrf_gbtrs.exe cspike_gbsv.exe
pivoting: dspike_gbsv.exe dspike_gbtrfp_gbtrsp.exe cspike_gbsv.exe
double: dspike_gbsv.exe dspike_gbtrf_gbtrs.exe
complex: cspike_gbsv.exe 

%.exe: %.c
	$(CC) $< $(CFLAGS) $(INCL) $(LIB) -o $@

#==========================================
# Clean up directory: delete object files 
#==========================================
clean: 
	-@rm -f *.exe
