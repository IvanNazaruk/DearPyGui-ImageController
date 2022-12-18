from __future__ import annotations

import hashlib
import queue
import threading
import time
import traceback
from typing import TypeVar, Callable, Any, Dict

import dearpygui.dearpygui as dpg
import numpy as np
from PIL import Image as img
from PIL.Image import Image

texture_registry: int | str = 0


def set_texture_registry(texture_registry_tag: int | str):
    global texture_registry
    texture_registry = texture_registry_tag


TextureTag = TypeVar('TextureTag', bound=int)
ControllerImageTag = TypeVar('ControllerImageTag', bound=str)
ImageLoadStatus = TypeVar('ImageLoadStatus', bound=bool)
ImageControllerType = TypeVar('ImageControllerType', bound="ImageController")
SubscriptionTag = TypeVar('SubscriptionTag', bound=int)

texture_plug: TextureTag = None  # noqa


def get_texture_plug() -> TextureTag:
    global texture_plug
    if texture_plug is None:
        texture_plug = dpg.add_static_texture(width=1,
                                              height=1,
                                              default_value=[0] * 4,
                                              parent=texture_registry)
    return texture_plug


def image_to_dpg_texture(image: Image) -> TextureTag:
    rgba_image = image.convert("RGBA")

    img_1D_array = np.array(rgba_image, dtype=np.float32).ravel() / 255  # noqa
    dpg_texture_tag = dpg.add_static_texture(width=rgba_image.width,
                                             height=rgba_image.height,
                                             default_value=img_1D_array,
                                             parent=texture_registry)

    rgba_image.close()
    del img_1D_array, rgba_image
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
        :param handler:
        :return:
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
                try:
                    dpg.delete_item(handler)
                except Exception:
                    pass
            del deletion_queue
        cls.__thread = False


class ImageInfo:
    image: Image
    width: int
    height: int
    # Tag an already loaded DPG texture with this picture.
    # If is_loaded is False, the texture plug will be used.
    texture_tag: TextureTag

    # Shows that there is no need to queue up,
    # since the picture is already being processed
    loading = False

    _controller: ImageControllerType
    tag_in_controller: str

    _is_loaded: ImageLoadStatus = False
    _last_time_visible: time.time = 0

    # If it is None, then the worker is not created/working
    _worker_id: int | None = None

    _subscribers: dict[SubscriptionTag, Callable[[ImageLoadStatus, TextureTag], Any]]

    def __init__(self,
                 image: Image,
                 width: int, height: int,
                 tag_in_controller: ControllerImageTag,
                 controller: ImageControllerType):
        self.image = image
        self.width = width
        self.height = height
        self.tag_in_controller = tag_in_controller
        self._controller = controller
        self._subscribers = dict()
        self.texture_tag = get_texture_plug()

    @property
    def last_time_visible(self):
        return self._last_time_visible

    @last_time_visible.setter
    def last_time_visible(self, value: time.time):
        self._last_time_visible = value
        self.create_worker()
        if not self.is_loaded and not self.loading:
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
    def is_loaded(self, value: bool):
        self._is_loaded = value
        for function in self._subscribers.values():
            try:
                function(value, self.texture_tag)
            except Exception:
                traceback.print_exc()
        if self._is_loaded is True:
            self.create_worker()

    def subscribe(self, function: Callable[[ImageLoadStatus, TextureTag], Any]) -> SubscriptionTag:
        """
        Subscribe to image status changes.
        Calls the function and transmits the image status and
        DPG texture tag, when changes:
        (True/False, TextureTag) = (Loaded/Unloaded, New dpg texture)
        """
        subscription_tag = dpg.generate_uuid()
        self._subscribers[subscription_tag] = function
        return subscription_tag

    def unsubscribe(self, subscription_tag: SubscriptionTag):
        """
        Unsubscribe from image status changes.
        If there are zero subscribers, this object and
        the association in the ImageController will be deleted.
        """
        if subscription_tag in self._subscribers:
            del self._subscribers[subscription_tag]
        if len(self._subscribers) == 0:
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
        self.texture_tag = get_texture_plug()

        self.is_loaded = False
        if old_dpg_tag != texture_plug:
            dpg.delete_item(old_dpg_tag)

        self._worker_id = None


class ImageController(Dict[ControllerImageTag, ImageInfo]):
    """
    Stores all hash pictures and associates it with ImageInfo.
    Also with the help of workers loads images into the DPG
    """
    loading_queue: queue.LifoQueue[ImageInfo]

    max_inactive_time: int | float
    unloading_check_sleep_time: int | float

    def __init__(self, max_inactive_time: int = 10, unloading_check_sleep_time: int | float = 1, number_image_loader_workers: int = 2, queue_max_size: int = None):
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

    def add(self, href: str | Image) -> tuple[ControllerImageTag, ImageInfo]:
        """
        :param href: File path or pillow Image
        :return:
        """

        if isinstance(href, str):
            image = img.open(href)
            image_tag = hashlib.md5(href.encode()).hexdigest()
        elif isinstance(href, Image):
            image = href
            image_tag = hashlib.md5(image.tobytes()).hexdigest()  # TODO: Better hash function
        else:
            raise ValueError(f"href must be an Image or str, not {type(href)}")

        # Checking if an image has already been added
        image_info = self.get(image_tag, None)
        if image_info:
            return image_tag, image_info

        image_info = ImageInfo(
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
                image_info.texture_tag = image_to_dpg_texture(image_info.image)
                image_info.is_loaded = True
            except Exception:  # TODO: ValueError: Operation on closed image
                traceback.print_exc()

            image_info.loading = False
            self.loading_queue.task_done()


default_image_controller = ImageController()


class ImageViewer:
    _view_window: int

    width: int
    height: int

    _theme: int = None
    _handler: int
    image_handler: int | str = None

    texture_tag: TextureTag
    info: ImageInfo

    deleted: bool = False
    group: int = None

    def __new__(cls, *args, **kwargs):
        if cls._theme is None:
            with dpg.theme() as cls._theme:
                with dpg.theme_component(dpg.mvAll, parent=cls._theme) as theme_component:
                    dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0, category=dpg.mvThemeCat_Core, parent=theme_component)
                    dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0, category=dpg.mvThemeCat_Core, parent=theme_component)
                    dpg.add_theme_style(dpg.mvStyleVar_CellPadding, 0, 0, category=dpg.mvThemeCat_Core, parent=theme_component)
                    dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0, category=dpg.mvThemeCat_Core, parent=theme_component)
                    dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0, category=dpg.mvThemeCat_Core, parent=theme_component)
        return super(ImageViewer, cls).__new__(cls)

    def __init__(self, href: str | Image, width: int = None, height: int = None, controller: ImageController = None):
        if controller is None:
            controller = default_image_controller
        self.texture_tag, self.info = controller.add(href)
        self.width, self.height = width, height
        with dpg.item_handler_registry() as self._handler:
            dpg.add_item_visible_handler(callback=self.update_last_time_visible, parent=self._handler)
        self.subscription_tag = self.info.subscribe(self.change_status)

    def update_last_time_visible(self):
        if self.deleted:
            return
        self.info.update_last_time_visible()

    def get_size(self) -> (int, int):
        if self.width and self.height:
            return self.width, self.height
        if not self.width and not self.height:
            return self.info.width, self.info.height
        if self.width:
            height = self.info.height * (self.width / self.info.width)
            height = int(height)
            return self.width, height
        if self.height:
            width = self.info.width * (self.height / self.info.height)
            width = int(width)
            return width, self.height

    def change_status(self, image_load_status: ImageLoadStatus, texture_tag: TextureTag):
        self.texture_tag = texture_tag
        # If deleted or not rendered
        if self.deleted or not self.group:
            return
        dpg.delete_item(self._view_window, children_only=True)
        if image_load_status:
            self._render_image()
        else:
            self._render_loading()

    def render(self, parent=0):
        width, height = self.get_size()
        with dpg.group(parent=parent) as self.group:
            dpg.bind_item_theme(self.group, self._theme)
            self._view_window = dpg.add_child_window(width=width,
                                                     height=height,
                                                     no_scrollbar=True)
            dpg.bind_item_handler_registry(self.group, self._handler)
        self.change_status(self.info.is_loaded, self.info.texture_tag)

    def _render_loading(self):
        self.dpg_image = None
        dpg.add_loading_indicator(parent=self._view_window)

    def _render_image(self):
        width, height = self.get_size()
        self.dpg_image = dpg.add_image(self.texture_tag,
                                       width=width,
                                       height=height,
                                       parent=self._view_window)
        if self.image_handler:
            dpg.bind_item_handler_registry(self.dpg_image, self.image_handler)

    def set_size(self, *, width: int = None, height: int = None):
        self.width = width
        self.height = height
        width, height = self.get_size()
        dpg.configure_item(self._view_window,
                           width=width,
                           height=height)
        if not self.dpg_image:
            return
        dpg.configure_item(self.dpg_image,
                           width=width,
                           height=height)

    def set_width(self, width: int = None):
        self.set_size(width=width, height=self.height)

    def set_height(self, height: int = None):
        self.set_size(width=self.width, height=height)

    def set_image_handler(self, handler: int | str):
        self.image_handler = handler
        if self.dpg_image:
            dpg.bind_item_handler_registry(self.dpg_image, self.image_handler)

    def delete(self):
        self.__del__()

    def __del__(self):
        if self.deleted:
            return
        self.deleted = True

        try:
            dpg.delete_item(self.group)
        except Exception:
            pass

        HandlerDeleter.add(self._handler)
        self.info.unsubscribe(self.subscription_tag)

        self.texture_tag = None  # noqa
        self.info = None  # noqa
        self.group = None  # noqa
        self._view_window = None  # noqa
