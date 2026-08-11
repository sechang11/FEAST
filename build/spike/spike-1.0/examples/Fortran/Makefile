include ../make.inc

help:
	@echo "Usage: make {all rall clean} "
	@echo "make all    -- compile all examples for this directory "
	@echo "make clean  -- clean all examples for this directory "
	@echo "Please set compiler and libraries paths, and change compiler options in ../../make.inc"
	@echo

ARCH:=none
ifeq ($(ARCH),none)
  ARCH:=x64
endif
#==============================================================
# Include the LIB (spike and  - lapack - blas)  
#==============================================================
LIB = $(LOCLIBS) $(SPIKE) $(FLIBS)
all: normal pivot

pivot: gbtrfp_gbtrsp gbsv
normal: gbtrf_gbtrs gbsv

gbtrfp_gbtrsp:
	$(FORT) $(FFLAGS) $(INCL) driver_dspike_gbtrfp_gbtrsp.f90 $(LIB) -o driver_dspike_gbtrfp_gbtrsp.exe
gbtrf_gbtrs:
	$(FORT) $(FFLAGS) $(INCL) driver_dspike_gbtrf_gbtrs.f90 $(LIB) -o driver_dspike_gbtrf_gbtrs.exe
gbsv:
	$(FORT) $(FFLAGS) $(INCL) driver_dspike_gbsv.f90 $(LIB) -o driver_dspike_gbsv.exe


#==========================================
# Clean up directory: delete object files 
#==========================================
clean: 
	rm -f *.o
	rm -f *.exe
