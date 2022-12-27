from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _typeshed import SupportsRead

from PIL import Image

from .controller import ImageViewer, ImageController, HandlerDeleter
from .controller import default_image_controller
from .controller import get_texture_plug, image_to_dpg_texture, set_texture_registry


def add_image(image: bytes | Path | SupportsRead[bytes] | Image,
              width: int = None,
              height: int = None,
              parent=0,
              controller: ImageController = None) -> ImageViewer:
    image_viewer = ImageViewer()
    image_viewer.set_controller(controller)
    image_viewer.load(image)
    image_viewer.set_size(width=width, height=height)
    image_viewer.create(parent=parent)
    return image_viewer
