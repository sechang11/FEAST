# Website and free calculator

A mirror of the FEAST site structure for this distribution, plus a calculator
that runs the real solver.

```bash
pip install fastapi "uvicorn[standard]" numpy scipy
python build_site.py                       # regenerate static/*.html
python -m uvicorn server:app --port 8010   # serve site + API
```

Then open <http://127.0.0.1:8010/>.

## Layout

```
build_site.py     one template + page content -> static/*.html
server.py         FastAPI: static files, plus /api/{bounds,estimate,solve,samples,limits}
static/style.css  hand-written, light and dark
static/*.js       calculator front end
shoot.py          screenshots pages via QtWebEngine (PySide6 already has it)
```

`static/*.html` is generated; edit `build_site.py`, not the output.

## The calculator runs the real thing

`/api/solve` calls the same `feastpy` code path as the desktop app, through the
same child-process runner, against the same `libfeast`. There is no separate web
implementation to drift out of sync — which is the reason the solver logic lives
in the package rather than in the GUI.

Verified against FEAST's own `system1` sample: the calculator returns the same
16 eigenvalues, 0.2167888…0.9897906, that the upstream Fortran driver prints.

## Free-tier limits

Set at the top of `server.py`. They are on **size and time, not features** —
dense to 500×500, sparse to 20,000 (400k nonzeros), 30s per solve. The
calculator does everything the app does; the wall is honest, and it is the
upgrade prompt.

## Deploying

The API needs the native library, so the box needs `libfeast` built for its
platform (`bash build/build-feast.sh`) and OpenBLAS present. Everything else is
static files.

Worth adding before this faces the internet:

- a rate limit per IP — a solve is real CPU work,
- a request-size limit at the proxy as well as in the app,
- more than one worker, since a solve occupies a request thread.
