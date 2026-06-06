from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image


def to_grayscale(image: Image) -> Image:
    return image.convert("L")


def threshold(image: Image, thresh: int = 128) -> Image:
    gray = image.convert("L")
    return gray.point(lambda x: 255 if x > thresh else 0, mode="1").convert("L")


def denoise(image: Image, size: int = 3) -> Image:
    from PIL import ImageFilter

    return image.filter(ImageFilter.MedianFilter(size=size))


def deskew(image: Image) -> Image:
    try:
        import pytesseract

        osd = pytesseract.image_to_osd(image, output_type=pytesseract.Output.DICT)
        angle = osd.get("rotate", 0)
        if angle and angle != 0:
            from PIL import Image as PILImage

            return image.rotate(
                -angle, expand=True, fillcolor=255, resample=PILImage.BICUBIC
            )
    except (ImportError, OSError):
        return image
    return image


def preprocess(image: Image, steps: list[str] | None = None) -> Image:
    if steps is None:
        steps = ["grayscale", "denoise", "threshold"]

    processors = {
        "grayscale": to_grayscale,
        "denoise": denoise,
        "threshold": threshold,
        "deskew": deskew,
    }

    result = image
    for step in steps:
        if step in processors:
            result = processors[step](result)
    return result
