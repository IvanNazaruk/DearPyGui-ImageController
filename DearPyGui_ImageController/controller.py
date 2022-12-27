from __future__ import annotations

import hashlib
import queue
import threading
import time
import traceback
from pathlib import Path
from typing import TYPE_CHECKING
from typing import TypeVar, Callable, Any, Dict

if TYPE_CHECKING:
    from _typeshed import SupportsRead

import dearpygui.dearpygui as dpg

try:
    import numpy as np


    def _image_to_1d_array(image: Image) -> np.array:
        return np.array(image, dtype=np.float32).ravel() / 255  # noqa
except ModuleNotFoundError:
    import logging

    logger = logging.getLogger('DearPyGui_ImageController')
    logger.warning("numpy not installed. In DPG images will take longer to load (about 8 times slower).")


    def _image_to_1d_array(image: Image) -> list:
        img_1D_array = []
        image_data = image.getdata()
        if len(image_data) == 3:
            for pixel in image_data:
                img_1D_array.extend((pixel[0] / 255, pixel[1] / 255, pixel[2] / 255, 1))
        else:
            for pixel in image_data:
                img_1D_array.extend((pixel[0] / 255, pixel[1] / 255, pixel[2] / 255, pixel[3] / 255))
        del image_data
        return img_1D_array

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
        if self._controller is None:
            return None
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

    def add(self, image: str | bytes | Path | SupportsRead[bytes] | Image) -> tuple[ControllerImageTag, ImageInfo]:
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
    width: int | None = None
    height: int | None = None

    _theme: int = None

    group: int = None
    _view_window: int = None

    dpg_image: int | None = None
    texture_tag: TextureTag = None
    info: ImageInfo | None = None
    subscription_tag: SubscriptionTag = None

    _visible_handler: int = None
    image_handler: int | str | None = None
    _controller: ImageController | None = None

    @classmethod
    def _get_theme(cls) -> int:
        if cls._theme is None:
            with dpg.theme() as cls._theme:
                with dpg.theme_component(dpg.mvAll, parent=cls._theme) as theme_component:
                    dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0, category=dpg.mvThemeCat_Core, parent=theme_component)
                    dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0, category=dpg.mvThemeCat_Core, parent=theme_component)
                    dpg.add_theme_style(dpg.mvStyleVar_CellPadding, 0, 0, category=dpg.mvThemeCat_Core, parent=theme_component)
                    dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0, category=dpg.mvThemeCat_Core, parent=theme_component)
                    dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0, category=dpg.mvThemeCat_Core, parent=theme_component)
        return cls._theme

    def _get_visible_handler(self) -> int:
        if not self._visible_handler:
            with dpg.item_handler_registry() as self._visible_handler:
                dpg.add_item_visible_handler(callback=self.update_last_time_visible, parent=self._visible_handler)
        return self._visible_handler

    def update_last_time_visible(self):
        if self.info:
            self.info.update_last_time_visible()

    def get_size(self) -> (int, int):
        if self.width and self.height:
            return self.width, self.height
        if not self.info:
            if self.width:
                return self.width, self.unload_height
            if self.height:
                return self.unload_width, self.height
            return self.unload_width, self.unload_height
        if not self.width and not self.height:
            return self.info.width, self.info.height
        if self.width:
            height = int(self.info.height * (self.width / self.info.width))
            return self.width, height
        if self.height:
            width = int(self.info.width * (self.height / self.info.height))
            return width, self.height

    def set_size(self, *, width: int = None, height: int = None):
        '''
        Set the size of the viewer when the image is loaded in the viewer
        (is also used when dimensions are set and do not equal None).
        If the dimensions are None the size of the picture will be used.
        If one of the dimensions is None, it will be proportionally
        changed in the ratio of the image size to the other dimension.
        If a viewer is created, the changes are applied instantly.

        :param width: Viewer width. Used when the image is loaded in the viewer or another dimension is also set
        :param height: Viewer height. Used when the image is loaded in the viewer or another dimension is also set
        '''
        self.width = width
        self.height = height
        if not self.group:
            return
        width, height = self.get_size()
        try:
            dpg.configure_item(self._view_window,
                               width=width,
                               height=height)
            if self.dpg_image:
                dpg.configure_item(self.dpg_image,
                                   width=width,
                                   height=height)
        except Exception:
            traceback.print_exc()

    def set_width(self, width: int = None):
        '''
        It uses the function `.set_size` and only sets the width, the width will not be changed

        :param width: Viewer width. Used when the image is loaded in the viewer or another dimension is also set
        '''
        self.set_size(width=width, height=self.height)

    def set_height(self, height: int = None):
        '''
        It uses the function `.set_size` and only sets the height, the width will not be changed

        :param height: Viewer height. Used when the image is loaded in the viewer or another dimension is also set
        '''
        self.set_size(width=self.width, height=height)

    def __init__(self,
                 image: str | bytes | Path | SupportsRead[bytes] | Image = None,
                 controller: ImageController = None,
                 unload_width: int = 100,
                 unload_height: int = 100):
        '''
        Image viewer, which automatically unloads the image
        from the DPG if the user can't see it.
        You can specify some arguments at creation if you want

        :param image: Pillow Image or the path to the image, or any other object that Pillow can open
        :param controller: Set `None` if you want to use the default controller
        :param unload_width: Viewer width, when the image is not yet loaded (or unloaded) from the viewer
        :param unload_height: Viewer height, when the image is not yet loaded (or unloaded) from the viewer
        '''
        self.unload_width = unload_width
        self.unload_height = unload_height
        if controller:
            self.set_controller(controller)
        if image:
            self.load(image)

    def set_controller(self, controller: ImageController = None):
        '''
        Set the image controller.
        The next image loading will be done through this controller.

        :param controller: Set `None` if you want to set the default controller
        '''
        self._controller = controller

    def set_image_handler(self, handler: int | str = None):
        '''
        Set the DPG handler on the image.
        It will work even if the image is not loaded into the viewer.
        Not working during image loading.

        :param handler: DPG item handler
        '''
        self.image_handler = handler
        if self.dpg_image:
            try:
                dpg.bind_item_handler_registry(self.dpg_image, self.image_handler)
            except Exception:
                pass

    def load(self, image: str | bytes | Path | SupportsRead[bytes] | Image | None):
        '''
        Loads the image into the viewer, if an image already exists
        it will be replaced by the new image.
        If the `image` argument is None, the texture plug will be loaded,
        this allows further use of the image handler.

        :param image: Pillow Image or the path to the image, or any other object that Pillow can open
        '''
        if self.info:
            self.info.unsubscribe(self.subscription_tag)
            self.info = None
            # Changing view to loading
            self.change_status(False)

        controller = self._controller
        if controller is None:
            controller = default_image_controller

        # If the image is set, loads it and if possible sets it in the viewer
        # Else it puts the texture plug
        if image:
            self.texture_tag, self.info = controller.add(image)
            self.subscription_tag = self.info.subscribe(self.change_status)
            if self.group:
                self.change_status(self.info.is_loaded, self.info.texture_tag)
        else:
            if self.group:
                self.change_status(True)
        self.set_size(width=self.width, height=self.height)

    def unload(self):
        '''
        Unload the loaded image from the viewer.
        The texture plug will be loaded, the image handler will continue to work.
        '''
        self.load(None)

    def create(self,
               width: int = None,
               height: int = None,
               unload_width: int = None,
               unload_height: int = None,
               parent=0):
        '''
        Creates a viewer in the DPG, if it has already been created,
        moves it to a new place (deletes the old).
        If you have pre-specified the dimensions, you don't have to set them here.

        :param width: Viewer width. Used when the image is loaded in the viewer or another dimension is also set
        :param height: Viewer height. Used when the image is loaded in the viewer or another dimension is also set
        :param unload_width: Viewer width, when the image is not yet loaded (or unloaded) from the viewer. Not used if the size is set (`width` and `height` is not None)
        :param unload_height: Viewer height, when the image is not yet loaded (or unloaded) from the viewer. Not used if the size is set (`width` and `height` is not None)
        :param parent: Parent to add this item to. (runtime adding)
        '''
        if width is not None:
            self.width = width
        if height is not None:
            self.width = height
        if unload_height is not None:
            self.unload_height = unload_height
        if unload_width is not None:
            self.unload_width = unload_width

        if self.group:
            try:  # If it was deleted with DPG
                dpg.delete_item(self.group)
            except Exception:
                pass
        width, height = self.get_size()
        with dpg.group(parent=parent) as self.group:
            dpg.bind_item_theme(self.group, self._get_theme())
            self._view_window = dpg.add_child_window(width=width,
                                                     height=height,
                                                     no_scrollbar=True,
                                                     parent=self.group)
            dpg.bind_item_handler_registry(self.group, self._get_visible_handler())

        if self.info:
            self.change_status(self.info.is_loaded, self.info.texture_tag)
        else:
            self.change_status(True)

    def change_status(self, image_load_status: ImageLoadStatus, texture_tag: TextureTag = None):
        if texture_tag is None:
            texture_tag = get_texture_plug()
        self.texture_tag = texture_tag
        if not self.group:  # If not created
            return
        try:  # If it was deleted with DPG
            dpg.delete_item(self._view_window, children_only=True)
            if image_load_status:
                self._render_image()
            else:
                self._render_loading()
        except Exception:
            traceback.print_exc()

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

    def delete(self):
        '''
        Deletes everything that was created by this object,
        namely: the viewer (DPG elements), handlers.
        Also resets all variables (except `unload_width` and `unload_height`)
        '''
        self.__del__()

    def __del__(self):
        if self.group:
            try:  # If it was deleted with DPG
                dpg.delete_item(self.group)
            except Exception:
                pass
        self.width = None
        self.height = None

        self.group = None  # noqa
        self._view_window = None  # noqa
        self.texture_tag = None  # noqa

        if self.info:
            self.info.unsubscribe(self.subscription_tag)

        self.info = None  # noqa
        self.subscription_tag = None  # noqa

        if self._visible_handler:
            HandlerDeleter.add(self._get_visible_handler())
            self._visible_handler = None  # noqa
        self.image_handler = None
        self._controller = None
