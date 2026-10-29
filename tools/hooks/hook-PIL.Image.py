"""Pillow is used for RGBA transforms and JPEG EXIF, not a general viewer."""

# TIFF supplies the EXIF directory decoder used by JPEG. Keep Pillow's basic
# preinitialization plugins, without collecting every optional native codec.
hiddenimports = [
    'PIL.BmpImagePlugin', 'PIL.GifImagePlugin', 'PIL.JpegImagePlugin',
    'PIL.PpmImagePlugin', 'PIL.PngImagePlugin', 'PIL.TiffImagePlugin',
]
