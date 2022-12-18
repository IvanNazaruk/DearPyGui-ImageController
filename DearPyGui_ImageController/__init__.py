from __future__ import annotations

from PIL import Image

from .controller import ImageViewer, ImageController
from .controller import default_image_controller
from .controller import get_texture_plug, image_to_dpg_texture, set_texture_registry


def add_image(href: str | Image.Image, width: int = None, height: int = None, parent=0) -> ImageViewer:
    image_viewer = ImageViewer(href, width, height)
    image_viewer.render(parent=parent)
    return image_viewer
