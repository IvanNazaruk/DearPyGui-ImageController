import dearpygui.dearpygui as dpg
from PIL import Image

import DearPyGui_ImageController as dpg_img
from DearPyGui_ImageController.tools import get_texture_size


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
    monkeypatch.setattr(dpg_img.tools, 'image_to_dpg_texture', lambda *args: created.append(args[1]) or original(*args))
    viewer, image_info = create_viewer(controller, width=50)
    for width in range(50, 1001, 10):
        viewer.set_width(width)
        show_frame(viewer, controller)
    print('textures created for 96 resize steps:', created)
    assert image_info.texture_size == (1000, 500)
    assert len(created) <= 10
