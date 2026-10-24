"""In-process Tesseract through its C API (ctypes).

pytesseract starts a tesseract process and reloads the language model for every crop; an inspection reads ~90
small crops, so on a 1-vCPU cloud container most of the time went into process start-up. This module drives the
very same libtesseract with the same settings (page segmentation mode, whitelist, default engine), keeping one
initialised engine per OCR thread. ``available()`` is False when the library cannot be loaded (e.g. a Windows
install without the DLL on PATH); the engine then falls back to pytesseract. Set ``EAGLE_EYE_OCR=cli`` to force
the subprocess path.
"""
import atexit
import ctypes
import ctypes.util
import os
import threading

import numpy as np

_lib = None
_err = None
_local = threading.local()
_lock = threading.Lock()
_apis = []                      # every engine created, released at exit (libtesseract warns about leaks otherwise)


def _tess_dir():
    import config
    cmd = config.find_tesseract()
    return os.path.dirname(cmd) if cmd else None


def _candidates():
    yield os.environ.get("TESSERACT_LIB")
    yield ctypes.util.find_library("tesseract")
    d = _tess_dir()
    if d and os.name == "nt":                   # UB-Mannheim installer: DLL next to tesseract.exe
        yield os.path.join(d, "libtesseract-5.dll")
    yield from ("libtesseract.so.5", "libtesseract.so", "libtesseract.5.dylib", "/opt/homebrew/lib/libtesseract.dylib",
                "/usr/local/lib/libtesseract.dylib")


def _load():
    global _lib, _err
    if _lib is not None or _err is not None:
        return _lib
    with _lock:
        if _lib is not None or _err is not None:
            return _lib
        if os.environ.get("EAGLE_EYE_OCR", "").lower() == "cli":
            _err = "disabled by EAGLE_EYE_OCR=cli"
            return None
        for name in _candidates():
            if not name:
                continue
            try:
                lib = ctypes.CDLL(name)
            except OSError:
                continue
            V, P, I, S = ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, None
            sig = {
                "TessVersion": ([], P),
                "TessBaseAPICreate": ([], V),
                "TessBaseAPIDelete": ([V], S),
                "TessBaseAPIInit3": ([V, P, P], I),
                "TessBaseAPISetPageSegMode": ([V, I], S),
                "TessBaseAPISetVariable": ([V, P, P], I),
                "TessBaseAPISetImage": ([V, V, I, I, I, I], S),
                "TessBaseAPIGetUTF8Text": ([V], V),
                "TessBaseAPIClear": ([V], S),
                "TessDeleteText": ([V], S),
            }
            try:
                for fn, (args, res) in sig.items():
                    f = getattr(lib, fn)
                    f.argtypes, f.restype = args, res
            except AttributeError:
                continue
            _lib = lib
            return _lib
        _err = "libtesseract not found"
        return None


def _api():
    a = getattr(_local, "api", None)
    if a is None:
        lib = _load()
        a = lib.TessBaseAPICreate()
        data = None
        if os.name == "nt" and not os.environ.get("TESSDATA_PREFIX") and _tess_dir():
            data = os.path.join(_tess_dir(), "tessdata").encode()
        if lib.TessBaseAPIInit3(a, data, b"eng") != 0:
            lib.TessBaseAPIDelete(a)
            raise RuntimeError("libtesseract could not load the 'eng' language data")
        lib.TessBaseAPISetVariable(a, b"debug_file", os.devnull.encode())   # tiny-crop warnings stay quiet
        _local.api = a
        with _lock:
            _apis.append(a)
    return a


@atexit.register
def _release():
    if _lib is not None:
        while _apis:
            _lib.TessBaseAPIDelete(_apis.pop())


def available():
    """True when libtesseract loads and initialises (checked once per process)."""
    if _load() is None:
        return False
    try:
        _api()
        return True
    except Exception as e:  # noqa: BLE001
        global _err
        _err = str(e)
        return False


def version():
    lib = _load()
    return lib.TessVersion().decode() if lib else None


def image_to_string(img, psm, whitelist):
    """Same result as ``pytesseract.image_to_string(img, config=f"--psm {psm} -c tessedit_char_whitelist=...")``."""
    lib = _load()
    a = _api()
    img = np.ascontiguousarray(img, dtype=np.uint8)
    h, w = img.shape[:2]
    bpp = 1 if img.ndim == 2 else img.shape[2]
    lib.TessBaseAPISetPageSegMode(a, int(psm))
    lib.TessBaseAPISetVariable(a, b"tessedit_char_whitelist", whitelist.encode())
    lib.TessBaseAPISetImage(a, img.ctypes.data, w, h, bpp, img.strides[0])
    p = lib.TessBaseAPIGetUTF8Text(a)
    try:
        return ctypes.string_at(p).decode("utf-8", "replace") if p else ""
    finally:
        if p:
            lib.TessDeleteText(p)
        lib.TessBaseAPIClear(a)
