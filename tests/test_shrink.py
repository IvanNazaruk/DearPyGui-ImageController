import time

import dearpygui.dearpygui as dpg
import pytest
from PIL import Image

import DearPyGui_ImageController as dpg_img


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(time, 'time', lambda: now[0])
    return now


def create_viewer(controller, **size):
    with dpg.window():
        viewer = dpg_img.add_image(Image.new('RGB', (1000, 500), 'red'), controller=controller, **size)
    return viewer, controller[next(iter(controller))]


def show_frame(viewer, controller):
    viewer.update_last_time_visible()
    controller.load_images()


def wait(clock, viewer, controller, seconds):
    """Visible frames while time passes"""
    for _ in range(int(seconds)):
        clock[0] += 1
        show_frame(viewer, controller)


def test_headroom_is_dropped_after_the_size_settles(controller, clock):
    viewer, image_info = create_viewer(controller, width=100)
    show_frame(viewer, controller)
    viewer.set_width(300)
    show_frame(viewer, controller)
    assert image_info.texture_size == (450, 225)

    wait(clock, viewer, controller, 9)
    assert image_info.texture_size == (450, 225)
    wait(clock, viewer, controller, 2)
    assert image_info.texture_size == (300, 150)


def test_texture_shrinks_after_the_view_shrinks(controller, clock):
    viewer, image_info = create_viewer(controller, width=400)
    show_frame(viewer, controller)
    viewer.set_width(100)
    show_frame(viewer, controller)
    wait(clock, viewer, controller, 11)
    assert image_info.texture_size == (100, 50)
    assert len(image_info.frame_textures) == 1


def test_resizing_again_restarts_the_delay(controller, clock):
    viewer, image_info = create_viewer(controller, width=400)
    show_frame(viewer, controller)
    viewer.set_width(200)
    wait(clock, viewer, controller, 8)
    viewer.set_width(100)
    wait(clock, viewer, controller, 8)
    assert image_info.texture_size == (400, 200)
    wait(clock, viewer, controller, 3)
    assert image_info.texture_size == (100, 50)


def test_small_difference_is_kept(controller, clock):
    viewer, image_info = create_viewer(controller, width=100)
    show_frame(viewer, controller)
    viewer.set_width(95)
    wait(clock, viewer, controller, 20)
    assert image_info.texture_size == (100, 50)


def test_disabled_with_none(controller, clock):
    controller.shrink_delay = None
    viewer, image_info = create_viewer(controller, width=400)
    show_frame(viewer, controller)
    viewer.set_width(100)
    wait(clock, viewer, controller, 20)
    assert image_info.texture_size == (400, 200)
