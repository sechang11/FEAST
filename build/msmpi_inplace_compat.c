/* MPI_IN_PLACE translation for gfortran + MS-MPI.
 *
 * PFEAST calls MPI_ALLREDUCE(MPI_IN_PLACE, ...) at 222 sites, and that
 * combination is silently broken when the caller is compiled with mingw
 * gfortran against MS-MPI: a five-line reproducer returns zeros instead of the
 * reduction, and PFEAST then dies at its first collective.
 *
 * Why. In the MPICH convention that MS-MPI follows, the Fortran MPI_IN_PLACE
 * is not a value but an ADDRESS: the runtime recognises "in place" by
 * comparing the incoming buffer pointer against the address of a well-known
 * variable in COMMON /MPIPRIV1/. MS-MPI's mpif.h marks that block
 *
 *     !DEC$ ATTRIBUTES DLLIMPORT :: /MPIPRIV1/
 *
 * so Intel Fortran imports the runtime's own copy and the comparison works.
 * gfortran ignores !DEC$ directives entirely -- each gfortran program gets its
 * own private, zero-filled MPIPRIV1, whose address means nothing to msmpi.dll.
 * The runtime therefore treats the sentinel as an ordinary send buffer and
 * "reduces" from it.
 *
 * The fix is interception. This object defines mpi_allreduce_, the symbol
 * gfortran-compiled Fortran actually calls, so the linker resolves FEAST's
 * calls here instead of into the import library. When the send buffer is the
 * program's own Fortran sentinel, it is swapped for the C MPI_IN_PLACE, which
 * MS-MPI does recognise; everything else passes straight through. Handles
 * convert by cast -- on MS-MPI, MPI_*_f2c are literally casts, which is also
 * why plain two-buffer calls already worked without help.
 *
 * FEAST uses no other sentinel anywhere (grep: no MPI_BOTTOM, no
 * MPI_STATUS_IGNORE), so one wrapper covers the whole library. Linux and
 * macOS bindings do this translation themselves; this file is compiled into
 * libpfeast on Windows only.
 */
#include <mpi.h>

/* COMMON /MPIPRIV1/ is MPI_BOTTOM, MPI_IN_PLACE, MPI_STATUS_IGNORE, in that
 * order; gfortran lowercases the block name and appends one underscore. */
extern int mpipriv1_[];

void mpi_allreduce_(void *sendbuf, void *recvbuf, int *count, int *datatype,
                    int *op, int *comm, int *ierr)
{
    if (sendbuf == (void *) &mpipriv1_[1])
        sendbuf = MPI_IN_PLACE;
    *ierr = MPI_Allreduce(sendbuf, recvbuf, *count,
                          MPI_Type_f2c(*datatype),
                          MPI_Op_f2c(*op),
                          MPI_Comm_f2c(*comm));
}
