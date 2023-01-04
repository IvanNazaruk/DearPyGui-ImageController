from __future__ import annotations

import hashlib
import queue
import threading
import time
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Type
from typing import TypeVar, Dict

import dearpygui.dearpygui as dpg

if TYPE_CHECKING:
    from _typeshed import SupportsRead
    from .viewers import ImageViewerCreator
    from .tools import TextureTag

from PIL import Image as img
from PIL.Image import Image

from . import tools

ImageControllerTag = TypeVar('ImageControllerTag', bound=str)
ImageLoadStatus = TypeVar('ImageLoadStatus', bound=bool)
ControllerType = TypeVar('ControllerType', bound="Controller")
SubscriptionTag = TypeVar('SubscriptionTag', bound=int)
ImageControllerType = TypeVar('ImageControllerType', bound="ImageController")


class ImageController:
    image: Image | None = None
    tag_in_controller: ImageControllerTag
    subscribers: Dict[SubscriptionTag, Type[ImageViewerCreator]]
    # Tag an already loaded DPG texture with this picture.
    # If loaded is False, the texture plug will be used.
    texture_tag: TextureTag

    last_time_visible: time.time = 0

    loading: bool = False
    loaded: bool = False

    def __init__(self, image: Image, tag_in_controller: ImageControllerTag, controller: ControllerType):
        self.image = image
        self.tag_in_controller = tag_in_controller
        self.controller = controller
        self.subscribers = dict()
        self.texture_tag = tools.get_texture_plug()

    def subscribe(self, image_viewer: Type[ImageViewerCreator]) -> SubscriptionTag:
        subscription_tag = dpg.generate_uuid()
        self.subscribers[subscription_tag] = image_viewer
        return subscription_tag

    def unsubscribe(self, subscription_tag: SubscriptionTag):
        if subscription_tag in self.subscribers:
            del self.subscribers[subscription_tag]
        if len(self.subscribers) == 0:
            del self.controller[self.tag_in_controller]
            self.image = None
            self.controller = None
            self.unload()

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
        if self.loaded or self.image is None:
            return
        if not self.loading:
            try:
                self.controller.loading_queue.put_nowait(self)
                self.loading = True
            except queue.Full:
                pass

    def load(self, texture_tag: TextureTag):
        self.texture_tag = texture_tag
        self.loaded = True
        self.loading = False
        for image_viewer in self.subscribers.values():
            try:
                image_viewer.show(self.texture_tag)  # noqa
            except Exception:
                traceback.print_exc()
        if self.image:
            self.controller.unload_queue.append(self)

    def unload(self):
        old_texture_tag = self.texture_tag
        self.texture_tag = tools.get_texture_plug()
        self.loaded = False
        self.loading = False
        for image_viewer in self.subscribers.values():
            try:
                image_viewer.hide()  # noqa
            except Exception:
                traceback.print_exc()

        if old_texture_tag != tools.get_texture_plug():
            try:
                dpg.delete_item(old_texture_tag)
            except Exception:
                traceback.print_exc()


class ImageUnloaderWorker:
    def __init__(self, unload_queue: list[ImageController], controller: ControllerType):
        self.queue = unload_queue
        self.controller = controller
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        while True:
            time.sleep(self.controller.unloading_check_sleep_time)
            for image_controller in self.queue:
                if image_controller.is_unloading_time():
                    image_controller.unload()
                    self.queue.remove(image_controller)


class ImageLoaderWorker:
    STOP = False

    def __init__(self, loading_queue: queue.LifoQueue[ImageController]):
        self.queue = loading_queue
        threading.Thread(target=self.loop, daemon=True).start()

    @staticmethod
    def load(image_controller: ImageController):
        if not image_controller.loading:
            return
        if image_controller.is_unloading_time() or image_controller.loaded:
            image_controller.loading = False
            return

        try:
            image_controller.load(
                tools.image_to_dpg_texture(image_controller.image)
            )
        except Exception:  # TODO: ValueError: Operation on closed image
            traceback.print_exc()

        image_controller.loading = False

    def loop(self):
        while not self.STOP:
            image_controller = self.queue.get()
            self.load(image_controller)
            self.queue.task_done()

    def stop(self):
        self.STOP = False


class Controller(Dict[ImageControllerTag, ImageController]):
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
        super().__init__()

        self.max_inactive_time = max_inactive_time
        self.unloading_check_sleep_time = unloading_check_sleep_time
        if queue_max_size is None:
            queue_max_size = number_image_loader_workers * 2

        self.loading_queue = queue.LifoQueue(maxsize=queue_max_size)
        self.loading_workers = []
        for _ in range(number_image_loader_workers):
            self.loading_workers.append(
                ImageLoaderWorker(self.loading_queue)
            )

        self.unload_queue = []
        self.unloading_worker = ImageUnloaderWorker(self.unload_queue, self)

    def add(self, image: str | bytes | Path | SupportsRead[bytes] | Image) -> tuple[ImageControllerTag, ImageController]:
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
            tag_in_controller=image_tag,
            controller=self
        )

        self[image_tag] = image_info
        return image_tag, image_info


default_controller = Controller()
