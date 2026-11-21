from __future__ import annotations

import atexit
import contextlib
import dearpygui.dearpygui as dpg
import threading
from typing import Iterator
from PIL.Image import Image, LANCZOS
from typing import Iterable, TypeVar

TextureTag = TypeVar('TextureTag', bound=int)

try:
    import numpy as np


    def _image_to_1d_array(image: Image) -> np.array:
        return np.array(image, dtype=np.float32).ravel() / 255  # noqa
except ModuleNotFoundError:
    import logging

    logger = logging.getLogger('DearPyGui_ImageController')
    logger.warning("numpy not installed. In DPG images will take longer to load (about 8 times slower).")


    def _image_to_1d_array(image: Image) -> list:  # image is always RGBA here
        return [value / 255 for value in image.tobytes()]

# Objects deleted during interpreter shutdown must not call DPG: its context is usually destroyed by then
interpreter_exiting = False


@atexit.register
def _mark_interpreter_exiting():
    global interpreter_exiting
    interpreter_exiting = True


texture_registry: int | str = 0
texture_plug: TextureTag = None  # noqa


def set_texture_registry(texture_registry_tag: int | str):
    global texture_registry
    texture_registry = texture_registry_tag


def get_texture_plug() -> TextureTag:
    global texture_plug
    if texture_plug is None:
        texture_plug = dpg.add_static_texture(width=1,
                                              height=1,
                                              default_value=[0] * 4,
                                              parent=texture_registry)
    return texture_plug


# MPO (phone JPEG) and multi-page TIFF also have several frames, but they are not animations
ANIMATED_FORMATS = ('GIF', 'PNG', 'WEBP')


def get_frame_count(image: Image) -> int:
    if image.format in ANIMATED_FORMATS and getattr(image, 'is_animated', False):
        return image.n_frames
    return 1


def get_frame_duration(image: Image) -> float:
    """Current frame duration in seconds. Like browsers, delays of 10 ms or less are shown as 100 ms"""
    duration = image.info.get('duration') or 0
    return (duration if duration > 10 else 100) / 1000


_frames_lock_creation = threading.Lock()


def iter_frames(image: Image) -> Iterator[tuple[Image, float]]:
    """
    Yields (frame, duration in seconds) for every frame by seeking the image itself.
    Locks the image while iterating and seeks it back to the first frame at the end.
    """
    with _frames_lock_creation:
        lock = image.__dict__.setdefault('_dpg_frames_lock', threading.Lock())
    with lock:
        try:
            for index in range(get_frame_count(image)):
                image.seek(index)
                image.load()  # WebP sets the frame duration only when the frame is loaded
                yield image, get_frame_duration(image)
        finally:
            image.seek(0)


BYTES_PER_PIXEL = 16  # DPG keeps texture pixels as 4 float32 values (RGBA)


def fit_to_byte_limit(size: tuple[int, int], frame_count: int = 1, max_bytes: int | None = None) -> tuple[int, int]:
    """Scales the size down, keeping proportions, until frame_count textures of that size take at most max_bytes"""
    if max_bytes is None:
        return size
    width, height = size
    max_pixels = max_bytes / (BYTES_PER_PIXEL * frame_count)
    if width * height <= max_pixels:
        return size
    scale = (max_pixels / (width * height)) ** 0.5
    return max(1, int(width * scale)), max(1, int(height * scale))


def get_texture_size(image_size: tuple[int, int], view_sizes: Iterable[tuple[int, int]], scale: float = 1) -> tuple[int, int]:
    """
    The smallest texture that covers every view size (times scale), but never bigger than the image itself.
    No view sizes means the full image size.
    """
    image_width, image_height = image_size
    view_sizes = list(view_sizes)
    if not view_sizes:
        return image_width, image_height
    width = max(view_width for view_width, _ in view_sizes) * scale
    height = max(view_height for _, view_height in view_sizes) * scale
    return max(1, min(int(width), image_width)), max(1, min(int(height), image_height))


def image_to_dpg_texture(image: Image, size: tuple[int, int] = None) -> TextureTag:
    rgba_image = image.convert("RGBA")
    if size and size != rgba_image.size:
        resized_image = rgba_image.resize(size, LANCZOS)
        rgba_image.close()
        rgba_image = resized_image
    img_1d_array = _image_to_1d_array(rgba_image)
    dpg_texture_tag = dpg.add_static_texture(width=rgba_image.width,
                                             height=rgba_image.height,
                                             default_value=img_1d_array,
                                             parent=texture_registry)

    rgba_image.close()
    del img_1d_array, rgba_image
    return dpg_texture_tag


class HandlerDeleter:
    """
    Prevents the DPG from shutting down suddenly.
    Removes the Handler after a period of time.
    """
    deletion_queue = []

    __thread: bool = False

    @classmethod
    def add(cls, handler: int | str):
        """
        Adds a handler to the deletion queue
        :param handler: DPG handler
        """
        if not cls.__thread:
            cls.__thread = True
            threading.Thread(target=cls._worker, daemon=True).start()
        cls.deletion_queue.append(handler)

    @classmethod
    def _worker(cls):
        while True:
            for _ in range(2):
                dpg.split_frame()

            if len(cls.deletion_queue) == 0:
                break

            deletion_queue = cls.deletion_queue.copy()
            cls.deletion_queue.clear()

            for _ in range(70):
                dpg.split_frame()

            for handler in deletion_queue:
                with contextlib.suppress(Exception):
                    dpg.delete_item(handler)
            del deletion_queue
        cls.__thread = False
