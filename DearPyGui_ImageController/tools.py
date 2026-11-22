from __future__ import annotations

import atexit
import contextlib
import functools
import dearpygui.dearpygui as dpg
import threading
import time
from typing import Iterator
from PIL.Image import BOX, Image, LANCZOS
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


# Background threads call DPG only inside `with dpg_access() as alive:`.
# dpg.destroy_context(), decorated below, waits until they leave it, and after it `alive` is False,
# because any DPG call without a context crashes the process. set_texture_registry() (called for every new context) makes it True again.
_dpg_access_condition = threading.Condition()
_dpg_users = 0
_dpg_alive = True


def dpg_is_alive() -> bool:
    return _dpg_alive and not interpreter_exiting


@contextlib.contextmanager
def dpg_access() -> Iterator[bool]:
    global _dpg_users
    with _dpg_access_condition:
        alive = dpg_is_alive()
        if alive:
            _dpg_users += 1
    try:
        yield alive
    finally:
        if alive:
            with _dpg_access_condition:
                _dpg_users -= 1
                _dpg_access_condition.notify_all()


def wait_for_background_threads(destroy_context):
    """
    Decorator for dpg.destroy_context (applied on import): before the context is destroyed,
    waits until the library's background threads finish their current DPG call and stops them from calling DPG.
    """
    if getattr(destroy_context, '_waits_for_background_threads', False):  # Already decorated
        return destroy_context

    @functools.wraps(destroy_context)
    def wrapper(*args, **kwargs):
        global _dpg_alive
        with _dpg_access_condition:
            _dpg_alive = False
            _dpg_access_condition.wait_for(lambda: _dpg_users == 0)
        return destroy_context(*args, **kwargs)

    wrapper._waits_for_background_threads = True
    return wrapper


dpg.destroy_context = wait_for_background_threads(dpg.destroy_context)


texture_registry: int | str = 0
texture_plug: TextureTag = None  # noqa


def set_texture_registry(texture_registry_tag: int | str):
    global texture_registry, _dpg_alive
    texture_registry = texture_registry_tag
    _dpg_alive = True


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


def get_image_lock(image: Image) -> threading.Lock:
    """One lock per PIL image object: seeking frames changes the object itself"""
    with _frames_lock_creation:
        return image.__dict__.setdefault('_dpg_frames_lock', threading.Lock())


def iter_frames(image: Image) -> Iterator[tuple[Image, float]]:
    """
    Yields (frame, duration in seconds) for every frame by seeking the image itself.
    Locks the image while iterating and seeks it back to the first frame at the end.
    """
    with get_image_lock(image):
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


def create_preview_texture(image: Image, width: int) -> TextureTag | None:
    """
    A tiny copy of the image (`width` px wide). DPG stretches it smoothly,
    so it looks like a blurred preview while the real texture loads.
    """
    if not width:
        return None
    width = min(width, image.width)
    height = max(1, round(width * image.height / image.width))
    with get_image_lock(image):
        preview = image.convert('RGBA').resize((width, height), BOX)
    return image_to_dpg_texture(preview)


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
    Deletes DPG item handler registries a few frames later.
    Deleting one right away, while DPG may still be running its handlers in the current frame, can crash DPG.
    """
    delay_frames = 70

    _queue: list[tuple[int, int | str]] = []  # (frame to delete at, handler)
    _lock = threading.Lock()
    _thread_running = False

    @classmethod
    def add(cls, handler: int | str):
        """
        Adds a handler to the deletion queue
        :param handler: DPG handler
        """
        if not dpg.is_dearpygui_running():  # No frames are rendered, so nothing can be using it
            with contextlib.suppress(Exception):
                dpg.delete_item(handler)
            return
        with cls._lock:
            cls._queue.append((dpg.get_frame_count() + cls.delay_frames, handler))
            if cls._thread_running:
                return
            cls._thread_running = True
        threading.Thread(target=cls._worker, daemon=True).start()

    @classmethod
    def _worker(cls):
        while True:
            time.sleep(0.05)
            with dpg_access() as alive:
                if not alive:  # The context and its handlers are gone
                    with cls._lock:
                        cls._queue = []
                        cls._thread_running = False
                    return
                running = dpg.is_dearpygui_running()
                frame = dpg.get_frame_count()
                with cls._lock:
                    due = [handler for delete_at, handler in cls._queue if not running or delete_at <= frame]
                    cls._queue = [item for item in cls._queue if item[1] not in due]
                    if not cls._queue:
                        cls._thread_running = False
                for handler in due:
                    with contextlib.suppress(Exception):
                        dpg.delete_item(handler)
            if not cls._thread_running:
                return
