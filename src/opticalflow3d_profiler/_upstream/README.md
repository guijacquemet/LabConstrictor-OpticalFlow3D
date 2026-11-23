# Vendored OpticalFlow3D (unchanged)

`calc_flow.py` is an unchanged copy of `src/Python/calc_flow.py` from
[aicjanelia/OpticalFlow3D](https://github.com/aicjanelia/OpticalFlow3D) at commit
`6b88604a75319d80002de47ca993ce8b55fb9c46`, distributed under the BSD 3-Clause licence in
`LICENSE` (Copyright (c) 2025, Howard Hughes Medical Institute).

- SHA-256 of `calc_flow.py`: `e40c6cfff644f2ae57a244e2ef1aa7c2a8e27cc7d361534182cdf1cb49338a05`.
  `opticalflow3d_profiler.flow_backend` refuses to run if the file differs.
- `_license.py` holds the licence text as a Python constant, because the LabConstrictor
  installer bundles only the `.py` files of `src/`.
- Modifications: none. The file is excluded from this project's Ruff and code-rule checks.
- Only `calc_flow3D` and `calc_flow2D` are called. `process_flow` is not used: it reads
  images by file-name pattern, guesses ImageJ metadata and calls `sys.exit` on errors; the
  profiler validates inputs first and writes the same `<name>_<vx|vy|vz|rel>_tNNNN.tiff`
  file layout itself.
- The module imports `natsort`, `pandas` and `tifffile` at import time, so `natsort` is a
  dependency of the application.
