"""Perception for the real-cabinet engine (spec section 4).

``preprocess.load_photo`` (EXIF transpose, ignore bands, quality), ``ocr.read_photo`` / ``ocr.read_region``
(PP-OCRv4 multi-pass reader) and ``decode`` (closed-vocabulary decoding, ferrule parser). Import the submodules
directly (``from vision import ocr``); this package stays import-light so registration and checks do not pay for
loading ONNX Runtime.
"""
