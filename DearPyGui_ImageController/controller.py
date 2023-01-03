from __future__ import annotations

import hashlib
import queue
import threading
import time
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Type
from typing import TypeVar, Dict

if TYPE_CHECKING:
    from _typeshed import SupportsRead
    from .viewers import ImageViewerCreator

from PIL import Image as img
from PIL.Image import Image

import dearpygui.dearpygui as dpg

from . import tools
from .tools import TextureTag

ControllerImageTag = TypeVar('ControllerImageTag', bound=str)
ImageLoadStatus = TypeVar('ImageLoadStatus', bound=bool)
ControllerType = TypeVar('ControllerType', bound="Controller")
SubscriptionTag = TypeVar('SubscriptionTag', bound=int)
ImageControllerType = TypeVar('ImageControllerType', bound="ImageController")


class ImageController:
    image: Image
    width: int
    height: int
    # Tag an already loaded DPG texture with this picture.
    # If is_loaded is False, the texture plug will be used.
    texture_tag: TextureTag

    # Shows that there is no need to queue up,
    # since the picture is already being processed
    loading = False

    _controller: ControllerType
    tag_in_controller: str

    _is_loaded: ImageLoadStatus = False
    _last_time_visible: time.time = 0

    # If it is None, then the worker is not created/working
    _worker_id: int | None = None

    _subscribers: dict[SubscriptionTag, Type[ImageViewerCreator]]

    def __init__(self,
                 image: Image,
                 width: int, height: int,
                 tag_in_controller: ControllerImageTag,
                 controller: ControllerType):
        self.image = image
        self.width = width
        self.height = height
        self.tag_in_controller = tag_in_controller
        self._controller = controller
        self._subscribers = dict()
        self.texture_tag = tools.get_texture_plug()

    @property
    def last_time_visible(self):
        return self._last_time_visible

    @last_time_visible.setter
    def last_time_visible(self, value: time.time):
        self._last_time_visible = value
        self.create_worker()
        if not self.is_loaded and not self.loading and self._controller:
            try:
                self._controller.loading_queue.put_nowait(self)
                self.loading = True
            except queue.Full:
                pass

    def update_last_time_visible(self):
        """
        Updates the last time the picture was visible.
        Also, if an image has been unloaded,
        it will be loaded back in, using the new worker
        """
        self.last_time_visible = time.time()

    @property
    def is_loaded(self):
        return self._is_loaded

    @is_loaded.setter
    def is_loaded(self, flag: bool):
        self._is_loaded = flag
        for image_viewer in self._subscribers.values():
            try:
                # function
                if flag:
                    image_viewer.show(self.texture_tag)  # noqa
                else:
                    image_viewer.hide()  # noqa
            except Exception:
                traceback.print_exc()
        if self._is_loaded is True:
            self.create_worker()

    def subscribe(self, image_viewer: Type[ImageViewerCreator]) -> SubscriptionTag:
        # """ TODO: rewrite
        # Subscribe to image status changes.
        # Calls the function and transmits the image status and
        # DPG texture tag, when changes:
        # (True/False, TextureTag) = (Loaded/Unloaded, New dpg texture)
        # """
        subscription_tag = dpg.generate_uuid()
        self._subscribers[subscription_tag] = image_viewer
        return subscription_tag

    def unsubscribe(self, subscription_tag: SubscriptionTag):
        """
        Unsubscribe from image status changes.
        If there are zero subscribers, this object and
        the association in the Controller will be deleted.
        """
        if subscription_tag in self._subscribers:
            del self._subscribers[subscription_tag]
        if len(self._subscribers) == 0:
            if self._controller is None:
                return
            if self.tag_in_controller not in self._controller:
                return
            del self._controller[self.tag_in_controller]
            self.image.close()
            self._controller = None  # noqa
            self.image = None  # noqa

    def is_unloading_time(self) -> bool:
        if self._controller is None:
            return True
        return (time.time() - self.last_time_visible) > self._controller.max_inactive_time

    def create_worker(self):
        if self._worker_id is None:
            if self._controller is None:
                return
            self._worker_id = dpg.generate_uuid()
            threading.Thread(target=self._worker, args=(self._worker_id,), daemon=True).start()

    def _worker(self, id: int):
        while self._worker_id == id:
            time.sleep(self._controller.unloading_check_sleep_time)
            if self.is_unloading_time():
                break
        if self._worker_id != id:
            return

        old_dpg_tag = self.texture_tag
        self.texture_tag = tools.get_texture_plug()

        self.is_loaded = False
        if old_dpg_tag != tools.texture_plug:
            dpg.delete_item(old_dpg_tag)

        self._worker_id = None


class Controller(Dict[ControllerImageTag, ImageController]):
    """
    Stores all hash pictures and associates it with ImageController.
    Also with the help of workers loads images into the DPG
    """
    loading_queue: queue.LifoQueue[ImageController]

    max_inactive_time: int | float
    unloading_check_sleep_time: int | float

    def __init__(self,
                 max_inactive_time: int = 4,
                 unloading_check_sleep_time: int | float = 1,
                 number_image_loader_workers: int = 2,
                 queue_max_size: int = None):
        """
        :param max_inactive_time: Time in seconds after which the picture will be unloaded from the DPG/RAM, If last time visible is not updated
        :param unloading_check_sleep_time: In this number of seconds the last visibility of the image will be checked
        :param number_image_loader_workers: Number of simultaneous loading of images
        :param queue_max_size: If not set, it will be equal to number_image_loader_workers * 2
        """
        self.max_inactive_time = max_inactive_time
        self.unloading_check_sleep_time = unloading_check_sleep_time
        if queue_max_size is None:
            queue_max_size = number_image_loader_workers * 2
        self.loading_queue = queue.LifoQueue(maxsize=queue_max_size)

        for _ in range(number_image_loader_workers):
            threading.Thread(target=self._image_loader_worker, daemon=True).start()

        super().__init__()

    def add(self, image: str | bytes | Path | SupportsRead[bytes] | Image) -> tuple[ControllerImageTag, ImageController]:
        """
        :param image: Pillow Image or the path to the image, or any other object that Pillow can open
        :return:
        """

        if isinstance(image, str):
            image_tag = hashlib.md5(image.encode()).hexdigest()
            image = img.open(image)
        elif isinstance(image, Image):
            image_tag = hashlib.md5(image.tobytes()).hexdigest()  # TODO: Better hash function
        else:
            raise ValueError(f"href must be an Image or str, not {type(image)}")

        # Checking if an image has already been added
        image_info = self.get(image_tag, None)
        if image_info:
            return image_tag, image_info

        image_info = ImageController(
            image=image,
            width=image.width, height=image.height,
            tag_in_controller=image_tag,
            controller=self
        )

        self[image_tag] = image_info
        return image_tag, image_info

    def _image_loader_worker(self):
        while True:
            image_info = self.loading_queue.get()

            if not image_info.loading:
                continue
            if image_info.is_unloading_time() or image_info.is_loaded:
                image_info.loading = False
                continue

            try:
                image_info.texture_tag = tools.image_to_dpg_texture(image_info.image)
                image_info.is_loaded = True
            except Exception:  # TODO: ValueError: Operation on closed image
                traceback.print_exc()

            image_info.loading = False
            self.loading_queue.task_done()


default_controller = Controller()
