import dearpygui.dearpygui as dpg
from PIL import Image

import DearPyGui_ImageController as dpg_img
from DearPyGui_ImageController.tools import BYTES_PER_PIXEL, fit_to_byte_limit, get_texture_size


def test_texture_size_is_the_biggest_view_size():
    assert get_texture_size((1000, 500), [(100, 50), (200, 30)]) == (200, 50)


def test_texture_size_is_never_bigger_than_the_image():
    assert get_texture_size((1000, 500), [(4000, 2000)]) == (1000, 500)
    assert get_texture_size((1000, 500), [(800, 400)], scale=1.5) == (1000, 500)


def test_no_views_means_full_size():
    assert get_texture_size((1000, 500), []) == (1000, 500)


def show_frame(viewer, controller):
    """What the visible handler and the loader thread do on a frame."""
    viewer.update_last_time_visible()
    controller.load_images()


def create_viewer(controller, **size):
    with dpg.window():
        viewer = dpg_img.add_image(Image.new('RGB', (1000, 500), 'red'), controller=controller, **size)
    image_info = controller[next(iter(controller))]
    return viewer, image_info


def test_texture_is_loaded_at_view_size(controller):
    viewer, image_info = create_viewer(controller, width=100)
    show_frame(viewer, controller)
    assert image_info.texture_size == (100, 50)
    config = dpg.get_item_configuration(image_info.texture_tag)
    assert (config['width'], config['height']) == (100, 50)


def test_view_without_size_gets_full_texture(controller):
    viewer, image_info = create_viewer(controller)
    show_frame(viewer, controller)
    assert image_info.texture_size == (1000, 500)


def test_growing_view_rebuilds_texture_with_headroom(controller):
    viewer, image_info = create_viewer(controller, width=100)
    show_frame(viewer, controller)
    small_texture = image_info.texture_tag

    viewer.set_width(300)
    show_frame(viewer, controller)
    assert image_info.texture_size == (450, 225)
    assert not dpg.does_item_exist(small_texture)
    assert dpg.get_item_configuration(viewer.dpg_image)['texture_tag'] == image_info.texture_tag
    assert controller.unload_queue.count(image_info) == 1


def test_shrinking_view_keeps_texture(controller):
    viewer, image_info = create_viewer(controller, width=300)
    show_frame(viewer, controller)
    texture = image_info.texture_tag
    viewer.set_width(100)
    show_frame(viewer, controller)
    assert image_info.texture_tag == texture


def test_step_by_step_resize_rebuilds_rarely(controller, monkeypatch):
    created = []
    original = dpg_img.tools.image_to_dpg_texture
    viewer, image_info = create_viewer(controller, width=50)  # creates the preview texture
    monkeypatch.setattr(dpg_img.tools, 'image_to_dpg_texture', lambda image, size: created.append(size) or original(image, size))
    for width in range(50, 1001, 10):
        viewer.set_width(width)
        show_frame(viewer, controller)
    print('textures created for 96 resize steps:', created)
    assert image_info.texture_size == (1000, 500)
    assert len(created) <= 10


def test_byte_limit_keeps_size_that_fits():
    assert fit_to_byte_limit((100, 50), max_bytes=100 * 50 * BYTES_PER_PIXEL) == (100, 50)
    assert fit_to_byte_limit((100, 50), max_bytes=None) == (100, 50)


def test_byte_limit_scales_down_keeping_proportions():
    assert fit_to_byte_limit((1000, 500), max_bytes=100 * 50 * BYTES_PER_PIXEL) == (100, 50)


def test_byte_limit_counts_every_frame():
    assert fit_to_byte_limit((1000, 500), frame_count=4, max_bytes=100 * 50 * BYTES_PER_PIXEL) == (50, 25)


def test_byte_limit_applies_to_loaded_texture(controller, monkeypatch):
    controller.max_texture_bytes = 100 * 50 * BYTES_PER_PIXEL
    viewer, image_info = create_viewer(controller)
    show_frame(viewer, controller)
    assert image_info.texture_size == (100, 50)

    created = []
    monkeypatch.setattr(dpg_img.tools, 'image_to_dpg_texture', lambda *args: created.append(args))
    assert not image_info.needs_bigger_texture()
    show_frame(viewer, controller)
    assert created == []


def test_growing_under_byte_limit_does_not_rebuild_every_frame(controller, monkeypatch):
    controller.max_texture_bytes = 200_000 * BYTES_PER_PIXEL
    with dpg.window():
        viewer = dpg_img.add_image(Image.new('RGB', (1000, 1000), 'red'), controller=controller, width=900, height=300)
    show_frame(viewer, controller)
    viewer.set_size(width=901, height=300)
    created = []
    original = dpg_img.tools.image_to_dpg_texture
    monkeypatch.setattr(dpg_img.tools, 'image_to_dpg_texture', lambda image, size: created.append(size) or original(image, size))
    for _ in range(20):
        show_frame(viewer, controller)
    assert len(created) <= 1
