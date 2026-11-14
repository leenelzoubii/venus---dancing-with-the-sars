"""Earthdata Login handling.

Rules of engagement:

* credentials live in ``~/.netrc`` (Windows: ``C:\\Users\\<you>\\.netrc``) or are typed once into an
  interactive prompt - **never** in the repo, code, logs or chat;
* nothing here ever prints a token, a username, or a password.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

NETRC_HINT = """
No Earthdata Login found.

Fix it in one of two ways:

  A) interactive (one prompt, nothing stored on disk):
       .venv\\Scripts\\python -c "import earthaccess; earthaccess.login()"

  B) persistent .netrc (recommended for streaming and GDAL):
       {netrc_path}
     containing exactly:
       machine urs.earthdata.nasa.gov
           login YOUR_USERNAME
           password YOUR_PASSWORD

Then re-run this script. Do not commit the .netrc file.
"""


def netrc_path() -> Path:
    """Where this platform's auth libraries look for credentials."""
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    return home / (".netrc" if os.name != "nt" else ".netrc")


def login(interactive: bool = True):
    """Return an authenticated ``earthaccess`` auth object, or raise with instructions."""
    import earthaccess

    try:
        auth = earthaccess.login(strategy="netrc", persist=False)
        if auth.authenticated:
            print("Earthdata Login: ok (netrc)")
            return auth
    except Exception:  # noqa: BLE001 - no netrc is a normal state, not an error
        pass

    if interactive and sys.stdin.isatty():
        print("Earthdata Login: prompting (credentials are not stored by this script)")
        auth = earthaccess.login(strategy="interactive", persist=False)
        if auth.authenticated:
            print("Earthdata Login: ok (interactive)")
            return auth

    raise RuntimeError(NETRC_HINT.format(netrc_path=netrc_path()))


def https_session():
    """An fsspec HTTPS filesystem that carries Earthdata auth - for streaming HDF5 by byte range."""
    import earthaccess

    session = getattr(earthaccess, "get_fsspec_https_session", None)
    if session is None:  # older earthaccess
        raise RuntimeError(
            "This earthaccess build has no get_fsspec_https_session(); upgrade it with "
            "'.venv\\Scripts\\python -m pip install --upgrade earthaccess'."
        )
    return session()


def open_remote(path: str, block_size: int = 8 * 1024 * 1024):
    """Open a remote file for *partial* reads (HDF5 needs seek + read, not a full download)."""
    fs = https_session()
    return fs.open(path, "rb", block_size=block_size, cache_type="readahead")
