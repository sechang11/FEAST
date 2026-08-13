# Web calculator + API.
#
# A Dockerfile rather than a buildpack, because this app is not an ordinary
# Python service: the calculator runs the real FEAST library, so the image
# needs a Fortran compiler and a BLAS, and libfeast has to be compiled here.
# No binary is committed -- a Fortran library built on one machine is not
# portable to another. Buildpacks differ on whether they read nixpacks.toml,
# and which system packages they provide; this removes the question.
#
# Railway, Render and Fly all prefer a Dockerfile when one is present.

FROM python:3.12-slim

# gfortran and OpenBLAS to build libfeast; build-essential for the C parts of
# the test driver. Removed from the layer immediately so they are not carried
# in the final image any longer than needed.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gfortran \
        libopenblas-dev \
        build-essential \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first: this layer is cached unless requirements.txt changes,
# so ordinary code edits do not reinstall SciPy every deploy.
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY . .

# Build the solver, then prove it works before the image is allowed to exist:
# run-test.sh checks the freshly built library against a matrix whose spectrum
# is known analytically. A deploy that ships a broken libfeast would otherwise
# look healthy until the first visitor pressed Solve.
RUN bash build/build-feast.sh --arch linux-x64 \
    && bash build/run-test.sh linux-x64

# The site's HTML is generated, not committed (web/static/*.html is
# gitignored). server.py can do this at startup too, but doing it here keeps
# the container's first request fast.
RUN python web/build_site.py

ENV PYTHONPATH=/app/python \
    PYTHONUNBUFFERED=1 \
    # FEAST is OpenMP-parallel and will otherwise claim every core it can see,
    # which on a shared host means one visitor starves the rest. server.py
    # divides this further across concurrent solves.
    OMP_NUM_THREADS=2

# $PORT is assigned by the platform at runtime, so the shell form is required
# to expand it; 8000 is the fallback for a plain `docker run`.
EXPOSE 8000
CMD python -m uvicorn server:app --app-dir web --host 0.0.0.0 --port ${PORT:-8000}
