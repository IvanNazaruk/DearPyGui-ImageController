import dearpygui.dearpygui as dpg
import pytest
from PIL import Image

import DearPyGui_ImageController as dpg_img
from DearPyGui_ImageController import tools


def texture_size(texture):
    config = dpg.get_item_configuration(texture)
    return config['width'], config['height']


def shown_texture(viewer):
    return dpg.get_item_configuration(viewer.dpg_image)['texture_tag']


def create_viewer(controller, image=None, **size):
    with dpg.window():
        viewer = dpg_img.add_image(image or Image.new('RGB', (1000, 500), 'red'), controller=controller, **size)
    return viewer, controller[next(iter(controller))]


def test_preview_is_16_px_wide_keeping_proportions(controller):
    _, image_info = create_viewer(controller)
    assert texture_size(image_info.preview_texture) == (16, 8)


def test_preview_is_not_bigger_than_a_tiny_image(controller):
    _, image_info = create_viewer(controller, Image.new('RGB', (4, 2)))
    assert texture_size(image_info.preview_texture) == (4, 2)


def test_preview_is_shown_until_loaded_and_after_unload(controller):
    viewer, image_info = create_viewer(controller, width=200)
    assert shown_texture(viewer) == image_info.preview_texture

    viewer.update_last_time_visible()
    controller.load_images()
    assert shown_texture(viewer) == image_info.texture_tag != image_info.preview_texture

    image_info.unload()
    assert shown_texture(viewer) == image_info.preview_texture
    assert dpg.does_item_exist(image_info.preview_texture)


def test_loading_indicator_is_centered_over_the_preview(controller):
    viewer, _ = create_viewer(controller, width=200)
    x, y = dpg.get_item_pos(viewer._loading_indicator)
    radius = dpg.get_item_configuration(viewer._loading_indicator)['radius']
    assert (x + radius * 13 / 2, y + radius * 13 / 2) == pytest.approx((100, 50), abs=1)  # DPG stores pos as whole pixels


def test_no_preview_when_disabled(controller):
    controller.preview_size = 0
    viewer, image_info = create_viewer(controller)
    assert image_info.preview_texture is None
    assert shown_texture(viewer) == tools.get_texture_plug()


def test_preview_is_deleted_with_the_last_viewer(controller):
    viewer, image_info = create_viewer(controller)
    preview = image_info.preview_texture
    viewer.load(None)
    assert not dpg.does_item_exist(preview)
