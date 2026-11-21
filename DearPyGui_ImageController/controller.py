from __future__ import annotations

import contextlib
import hashlib
import queue
import threading
import time
import traceback
from pathlib import Path
from typing import Type, TYPE_CHECKING
from typing import TypeVar

import dearpygui.dearpygui as dpg
from PIL import Image as img
from PIL.Image import LANCZOS, Image

from . import tools

if TYPE_CHECKING:
    from _typeshed import SupportsRead
    from .viewers import ImageViewerCreator
    from .tools import TextureTag

ImageControllerTag = TypeVar('ImageControllerTag', bound=str)
ImageLoadStatus = TypeVar('ImageLoadStatus', bound=bool)
ControllerType = TypeVar('ControllerType', bound="Controller")
SubscriptionTag = TypeVar('SubscriptionTag', bound=int)
ImageControllerType = TypeVar('ImageControllerType', bound="ImageController")

T_ImageViewerCreator = TypeVar('T_ImageViewerCreator', bound='ImageViewerCreator')


class ImageController:
    image: Image | None = None
    tag_in_controller: ImageControllerTag
    subscribers: dict[SubscriptionTag, Type[T_ImageViewerCreator]]
    # Tag of the DPG texture shown now (the current frame).
    # If loaded is False, the texture plug will be used.
    texture_tag: TextureTag

    texture_size: tuple[int, int] | None = None
    # Tiny blurred copy shown while the image is not loaded; lives as long as the image is in the controller
    preview_texture: TextureTag | None = None
    frame_count: int = 1
    # One texture per frame; a still image has one
    frame_textures: list[TextureTag]
    frame_durations: list[float]
    frame_index: int = 0
    next_frame_time: float = 0

    last_time_visible: time.time = 0
    # The texture size the viewers needed last time, and when it changed
    _last_needed_size: tuple[int, int] | None = None
    _needed_size_changed_at: float = 0

    loading: bool = False
    loaded: bool = False

    # When a view grows past the texture, the new texture is this much bigger, so resizing step by step doesn't rebuild it every time
    grow_headroom = 1.5
    # An oversized texture is rebuilt smaller only if it has this many times more pixels than needed
    shrink_min_ratio = 1.2
    # An animation stops when the image has not been visible for this many seconds
    animation_visible_timeout = 0.5

    def __init__(self, image: Image, tag_in_controller: ImageControllerTag, controller: ControllerType, frame_count: int = 1):
        self.image = image
        self.tag_in_controller = tag_in_controller
        self.controller = controller
        self.frame_count = frame_count
        self.subscribers = {}
        self.texture_tag = tools.get_texture_plug()
        self.frame_textures = []
        self.frame_durations = []

    def subscribe(self, image_viewer: Type[ImageViewerCreator]) -> SubscriptionTag:
        subscription_tag = dpg.generate_uuid()
        self.subscribers[subscription_tag] = image_viewer
        return subscription_tag

    def unsubscribe(self, subscription_tag: SubscriptionTag):
        if subscription_tag in self.subscribers:
            del self.subscribers[subscription_tag]
        if len(self.subscribers) == 0:
            del self.controller[self.tag_in_controller]
            self.unload()
            if self.preview_texture:
                with contextlib.suppress(Exception):
                    dpg.delete_item(self.preview_texture)
                self.preview_texture = None
            self.image = None
            self.controller = None

    def get_needed_texture_size(self, scale: float = 1) -> tuple[int, int]:
        view_sizes = []
        for image_viewer in list(self.subscribers.values()):
            get_size = getattr(image_viewer, 'get_size', None)
            if get_size is None:  # A viewer without a size needs the full image
                view_sizes = []
                break
            view_sizes.append(get_size())
        size = self._fit(tools.get_texture_size(self.image.size, view_sizes, scale))
        if scale != 1:
            # Clamping the headroom to the image and the byte limit can change its proportions,
            # so it may not cover the exact size any more; then the exact size is used
            exact_size = self._fit(tools.get_texture_size(self.image.size, view_sizes))
            if size[0] < exact_size[0] or size[1] < exact_size[1]:
                return exact_size
        return size

    def _fit(self, size: tuple[int, int]) -> tuple[int, int]:
        return tools.fit_to_byte_limit(size, self.frame_count, self.controller.max_texture_bytes)

    def needs_bigger_texture(self) -> bool:
        if not self.loaded or self.image is None or self.texture_size is None:
            return False
        needed_width, needed_height = self.get_needed_texture_size()
        texture_width, texture_height = self.texture_size
        return needed_width > texture_width or needed_height > texture_height

    def needs_smaller_texture(self) -> bool:
        """The texture is noticeably bigger than needed and the view size has not changed for `shrink_delay` seconds"""
        shrink_delay = self.controller.shrink_delay if self.controller else None
        if shrink_delay is None or not self.loaded or self.image is None or self.texture_size is None:
            return False
        needed_size = self.get_needed_texture_size()
        if needed_size != self._last_needed_size:
            self._last_needed_size = needed_size
            self._needed_size_changed_at = time.time()
            return False
        if time.time() - self._needed_size_changed_at < shrink_delay:
            return False
        texture_pixels = self.texture_size[0] * self.texture_size[1]
        return texture_pixels > needed_size[0] * needed_size[1] * self.shrink_min_ratio

    def is_unloading_time(self) -> bool:
        if self.image:
            return (time.time() - self.last_time_visible) > self.controller.max_inactive_time
        return True

    def update_last_time_visible(self):
        """
        Updates the last time the picture was visible.
        Also, if an image has been unloaded,
        it will be loaded back in, using the loader worker
        """
        self.last_time_visible = time.time()
        if self.image is None:
            return
        if self.loaded and not self.needs_bigger_texture() and not self.needs_smaller_texture():
            return
        if not self.loading:
            self.loading = True  # Before put: a waiting loader skips images that are not marked as loading
            try:
                self.controller.loading_queue.put_nowait(self)
            except queue.Full:
                self.loading = False

    def now_loading(self):
        for image_viewer in self.subscribers.values():
            try:
                image_viewer.now_loading()
            except Exception:
                traceback.print_exc()

    def load(self, frame_textures: list[TextureTag], frame_durations: list[float], texture_size: tuple[int, int] = None):
        with dpg.mutex():
            old_textures = self.frame_textures
            self.frame_textures = frame_textures
            self.frame_durations = frame_durations
            self.frame_index = 0
            self.next_frame_time = time.time() + frame_durations[0]
            self.texture_tag = frame_textures[0]
            self.texture_size = texture_size
            self.loaded = True
            self.loading = False
            if len(self.subscribers) == 0:
                self.unload()
            else:
                for image_viewer in list(self.subscribers.values()):
                    try:
                        image_viewer.show(self.texture_tag)  # noqa
                    except Exception:
                        traceback.print_exc()
            # Delete the previous (smaller) textures only after the viewers have switched to the new ones
            for texture in old_textures:
                with contextlib.suppress(Exception):
                    dpg.delete_item(texture)
        if self.image and self not in self.controller.unload_queue:
            self.controller.unload_queue.append(self)
        if self.loaded and self.image and len(frame_textures) > 1:
            self.controller.add_animation(self)

    def unload(self):
        with dpg.mutex():
            old_textures = self.frame_textures
            self.frame_textures = []
            self.frame_durations = []
            self.texture_tag = tools.get_texture_plug()
            self.texture_size = None
            self.loaded = False
            self.loading = False
            for image_viewer in self.subscribers.values():
                try:
                    image_viewer.hide()  # noqa
                except Exception:
                    traceback.print_exc()
            for texture in old_textures:
                with contextlib.suppress(Exception):
                    dpg.delete_item(texture)
        if self.controller:
            self.controller.remove_animation(self)

    def animate(self, now: float):
        """Shows the next frame if its time has come and the image is visible"""
        if len(self.frame_textures) < 2 or now - self.last_time_visible > self.animation_visible_timeout:
            return
        if now < self.next_frame_time:
            return
        if now - self.next_frame_time > 1:  # Was not visible for a while: continue from now instead of catching up
            self.next_frame_time = now
        with dpg.mutex():
            if len(self.frame_textures) < 2:  # Unloaded meanwhile
                return
            while self.next_frame_time <= now:
                self.frame_index = (self.frame_index + 1) % len(self.frame_textures)
                self.next_frame_time += self.frame_durations[self.frame_index]
            self.texture_tag = self.frame_textures[self.frame_index]
            for image_viewer in list(self.subscribers.values()):
                try:
                    image_viewer.set_frame(self.texture_tag)
                except Exception:
                    traceback.print_exc()


_workers_lock = threading.Lock()


class Worker:
    STOP = False
    THREAD_RUNNING = False

    def start_thread(self):
        with _workers_lock:
            self.STOP = False
            if self.THREAD_RUNNING:
                return
            self.THREAD_RUNNING = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            with _workers_lock:  # Checked together with start_thread, so a stop + start can't leave no thread running
                if self.STOP:
                    self.THREAD_RUNNING = False
                    return
            try:
                self.loop()
            except Exception:  # One failed step must not kill the thread for good
                traceback.print_exc()
                time.sleep(0.1)

    def loop(self):
        ...

    def stop(self):
        self.STOP = True


class ImageUnloaderWorker(Worker):
    def __init__(self, unload_queue: list[ImageController], controller: ControllerType):
        self.queue = unload_queue
        self.controller = controller

    def loop(self):
        for image_controller in list(self.queue):
            if image_controller.is_unloading_time():
                image_controller.unload()
                self.queue.remove(image_controller)
        time.sleep(self.controller.unloading_check_sleep_time)


class AnimationWorker(Worker):
    def __init__(self, controller: ControllerType):
        self.controller = controller

    def loop(self):
        self.controller.animate()
        time.sleep(0.01)


class ImageLoaderWorker(Worker):

    def __init__(self, loading_queue: queue.LifoQueue[ImageController]):
        self.queue = loading_queue

    @staticmethod
    def load(image_controller: ImageController):
        if not image_controller.loading:
            return
        try:
            ImageLoaderWorker._load(image_controller)
        finally:
            image_controller.loading = False  # Otherwise a failed image is never queued again

    @staticmethod
    def _load(image_controller: ImageController):
        reloading = image_controller.loaded
        growing = reloading and image_controller.needs_bigger_texture()
        shrinking = reloading and not growing and image_controller.needs_smaller_texture()
        if image_controller.is_unloading_time() or (reloading and not growing and not shrinking):
            return

        if not reloading:
            image_controller.now_loading()
        textures, durations = [], []
        try:
            size = image_controller.get_needed_texture_size(image_controller.grow_headroom if growing else 1)
            for frame, duration in tools.iter_frames(image_controller.image):
                textures.append(tools.image_to_dpg_texture(frame, size))
                durations.append(duration)
            image_controller.load(textures, durations, size)
        except Exception:  # TODO: ValueError: Operation on closed image
            traceback.print_exc()
            for texture in textures:
                with contextlib.suppress(Exception):
                    dpg.delete_item(texture)

    def loop(self):
        image_controller = self.queue.get()
        if self.STOP:
            self.queue.put(image_controller)
            return
        self.load(image_controller)
        self.queue.task_done()


class Controller(dict[ImageControllerTag, ImageController]):
    """
    Stores all hash pictures and associates it with ImageController.
    Also with the help of workers loads images into the DPG
    """
    loading_queue: queue.LifoQueue[ImageController]
    loading_workers: list[ImageLoaderWorker]

    unload_queue: list[ImageController]
    unloading_worker: ImageUnloaderWorker

    max_inactive_time: int | float
    unloading_check_sleep_time: int | float
    max_texture_bytes: int | None
    preview_size: int
    shrink_delay: int | float | None
    _disable_work_in_threads: bool = False
    _last_time_unload_check: time.time = time.time()

    @property
    def disable_work_in_threads(self):
        return self._disable_work_in_threads

    @disable_work_in_threads.setter
    def disable_work_in_threads(self, value: bool):
        self._disable_work_in_threads = value
        if value:
            for worker in self._workers():
                worker.stop()
            self.animation_worker.stop()
            return
        if self._threads_started or len(self) > 0:  # Before the first image the threads still start lazily
            self._threads_started = True
            for worker in self._workers():
                worker.start_thread()
            if self.animated_images:
                self.animation_worker.start_thread()

    def _workers(self) -> list[Worker]:
        return [*self.loading_workers, self.unloading_worker]

    def _start_threads_once(self):
        """Threads start with the first image, not on import"""
        if self._threads_started or self._disable_work_in_threads:
            return
        self._threads_started = True
        for worker in self._workers():
            worker.start_thread()

    def __init__(self,
                 max_inactive_time: int = 10,
                 unloading_check_sleep_time: int | float = 2.5,
                 number_image_loader_workers: int = 2,
                 queue_max_size: int = None,
                 disable_work_in_threads: bool = False,
                 max_texture_bytes: int | None = None,
                 preview_size: int = 16,
                 shrink_delay: int | float | None = 10):
        """
        :param max_inactive_time: Time in seconds after which the picture will be unloaded from the DPG/RAM, If last time visible is not updated
        :param unloading_check_sleep_time: In this number of seconds the last visibility of the image will be checked
        :param number_image_loader_workers: Number of simultaneous loading of images
        :param queue_max_size: If not set, it will be equal to number_image_loader_workers * 2
        :param disable_work_in_threads: Disables multi-threaded image un/loading, you have to use the `.load_images`/'.unload_images' function to un/load the images yourself
        :param max_texture_bytes: Maximum DPG texture memory for one image (all its frames together). A bigger image is loaded at a lower resolution. None - no limit
        :param preview_size: Width in pixels of the blurred preview shown while an image loads. 0 - no preview
        :param shrink_delay: After the view size stays the same for this many seconds, a texture bigger than needed (after the view shrank, or the 1.5x headroom after it grew) is rebuilt at the exact size. None - never
        """
        super().__init__()

        self.max_inactive_time = max_inactive_time
        self.max_texture_bytes = max_texture_bytes
        self.preview_size = preview_size
        self.shrink_delay = shrink_delay
        self.unloading_check_sleep_time = unloading_check_sleep_time
        if queue_max_size is None:
            queue_max_size = number_image_loader_workers * 2

        self.loading_queue = queue.LifoQueue(maxsize=queue_max_size)
        self.loading_workers = [
            ImageLoaderWorker(self.loading_queue)
            for _ in range(number_image_loader_workers)
        ]
        self.unload_queue = []
        self.unloading_worker = ImageUnloaderWorker(self.unload_queue, self)
        self.animated_images = []
        self.animation_worker = AnimationWorker(self)
        self._threads_started = False
        self._disable_work_in_threads = disable_work_in_threads

    def add(self, image: str | bytes | Path | SupportsRead[bytes] | Image) -> tuple[ImageControllerTag, ImageController]:
        """
        :param image: Pillow Image or the path to the image, or any other object that Pillow can open
        :return:
        """
        self._start_threads_once()

        if not isinstance(image, Image):
            image = img.open(image)
        image: Image

        image_hash = hashlib.blake2b(digest_size=16)
        image_hash.update(f'{image.mode} {image.size}'.encode())
        for frame, duration in tools.iter_frames(image):
            image_hash.update(frame.tobytes())
            image_hash.update(str(duration).encode())
        image_tag = image_hash.hexdigest()

        # Checking if an image has already been added
        if image_info := self.get(image_tag):
            return image_tag, image_info

        image_info = self[image_tag] = ImageController(
            image=image,
            tag_in_controller=image_tag,
            controller=self,
            frame_count=tools.get_frame_count(image)
        )
        image_info.preview_texture = tools.create_preview_texture(image, self.preview_size)
        return image_tag, image_info

    def add_animation(self, image_controller: ImageController):
        if image_controller not in self.animated_images:
            self.animated_images.append(image_controller)
        if not self._disable_work_in_threads:
            self.animation_worker.start_thread()

    def remove_animation(self, image_controller: ImageController):
        with contextlib.suppress(ValueError):
            self.animated_images.remove(image_controller)

    def animate(self):
        """
        Switches frames of visible animated images (GIF, APNG, animated WebP).
        The animation thread calls it; with `disable_work_in_threads` call it yourself every frame.
        """
        now = time.time()
        for image_controller in list(self.animated_images):
            image_controller.animate(now)

    def load_images(self, max_count: int = None):
        """
        Only works if `.disable_load_in_threads` == False.
        Loads images to the DPG that are in the queue to be displayed.

        :param max_count: (None - inf) Maximum number of images that can be loaded
        """
        if not self.disable_work_in_threads:
            return

        while self.loading_queue.not_empty:
            if max_count is not None:
                max_count -= 1
                if max_count < 0:
                    return

            try:
                image_controller = self.loading_queue.get(block=False)
            except queue.Empty:
                return

            ImageLoaderWorker.load(image_controller)

    def unload_images(self, max_count: int = None):
        """
        Only works if `.disable_load_in_threads` == False.
        Unloads loaded images (textures) from the DPG that are in the remove queue.

        :param max_count: (None - inf) Maximum number of images that can be uploaded
        """
        if not self.disable_work_in_threads:
            return
        if time.time() - self._last_time_unload_check < self.unloading_check_sleep_time:
            return
        self._last_time_unload_check = time.time()

        for image_controller in list(self.unload_queue):
            if image_controller.is_unloading_time():
                if max_count is not None:
                    max_count -= 1
                    if max_count < 0:
                        return
                image_controller.unload()
                self.unload_queue.remove(image_controller)


default_controller = Controller()
