"""Team Venus - reusable pipeline code for the NISAR "Dancing with the SARs" project.

Layout
------
config.py    load config/study_area.yaml, resolve a named AOI or an ad-hoc WKT
search.py    query ASF for NISAR products and group them into comparable stacks
nisar.py     open NISAR HDF5 products (local or streamed) and read backscatter slices
change.py    power -> dB, speckle filtering, difference/ratio, water masks
webexport.py write web-ready COGs / PNGs + bounds + metadata JSON
"""

__version__ = "0.1.0"
