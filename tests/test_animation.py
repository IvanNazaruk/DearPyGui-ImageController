import time

import dearpygui.dearpygui as dpg
import pytest
from PIL import Image

import DearPyGui_ImageController as dpg_img
from DearPyGui_ImageController import tools

COLORS = ['red', 'green', 'blue']


def save_animation(path, colors=COLORS, duration=50, size=(40, 20)):
    frames = [Image.new('RGB', size, color) for color in colors]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=duration, loop=0, lossless=True)  # lossless: WebP
    return path


@pytest.mark.parametrize('name', ['a.gif', 'a.png', 'a.webp'])
def test_animated_formats_have_frames_and_durations(tmp_path, name):
    image = Image.open(save_animation(tmp_path / name))
    frames = [(frame.convert('RGB').getpixel((0, 0)), duration) for frame, duration in tools.iter_frames(image)]
    assert [pixel for pixel, _ in frames] == [(255, 0, 0), (0, 128, 0), (0, 0, 255)]
    assert [duration for _, duration in frames] == [0.05] * 3
    assert image.tell() == 0


def test_multi_page_tiff_is_not_animated(tmp_path):
    image = Image.open(save_animation(tmp_path / 'a.tiff'))
    assert image.n_frames == 3
    assert tools.get_frame_count(image) == 1


def test_zero_delay_is_shown_as_100_ms(tmp_path):
    image = Image.open(save_animation(tmp_path / 'a.gif', duration=0))
    assert [duration for _, duration in tools.iter_frames(image)] == [0.1] * 3


def test_animations_with_same_first_frame_are_not_merged(controller, tmp_path):
    first = controller.add(save_animation(tmp_path / 'a.gif', ['red', 'green']))[0]
    second = controller.add(save_animation(tmp_path / 'b.gif', ['red', 'blue']))[0]
    assert first != second


def show_frame(viewer, controller):
    viewer.update_last_time_visible()
    controller.load_images()


def create_animated_viewer(controller, path, **size):
    with dpg.window():
        viewer = dpg_img.add_image(path, controller=controller, **size)
    return viewer, controller[next(iter(controller))]


def test_every_frame_gets_a_texture(controller, tmp_path):
    viewer, image_info = create_animated_viewer(controller, save_animation(tmp_path / 'a.gif'))
    show_frame(viewer, controller)
    assert len(image_info.frame_textures) == 3
    assert controller.animated_images == [image_info]


def test_animate_switches_frames_on_time(controller, tmp_path, monkeypatch):
    viewer, image_info = create_animated_viewer(controller, save_animation(tmp_path / 'a.gif'))
    show_frame(viewer, controller)
    shown = []
    for step in range(4):
        now = image_info.next_frame_time
        monkeypatch.setattr(time, 'time', lambda: now)
        image_info.last_time_visible = now
        controller.animate()
        shown.append(image_info.frame_textures.index(dpg.get_item_configuration(viewer.dpg_image)['texture_tag']))
    assert shown == [1, 2, 0, 1]


def test_invisible_animation_does_not_switch(controller, tmp_path, monkeypatch):
    viewer, image_info = create_animated_viewer(controller, save_animation(tmp_path / 'a.gif'))
    show_frame(viewer, controller)
    later = image_info.last_time_visible + 5
    monkeypatch.setattr(time, 'time', lambda: later)
    controller.animate()
    assert image_info.frame_index == 0


def test_unload_deletes_every_frame_and_reloads_from_file(controller, tmp_path):
    viewer, image_info = create_animated_viewer(controller, save_animation(tmp_path / 'a.gif'))
    show_frame(viewer, controller)
    textures = image_info.frame_textures
    image_info.unload()
    assert not any(dpg.does_item_exist(texture) for texture in textures)
    assert controller.animated_images == []

    show_frame(viewer, controller)
    assert len(image_info.frame_textures) == 3
    assert controller.animated_images == [image_info]


def test_byte_limit_counts_all_frames(controller, tmp_path):
    controller.max_texture_bytes = 3 * 10 * 5 * tools.BYTES_PER_PIXEL
    viewer, image_info = create_animated_viewer(controller, save_animation(tmp_path / 'a.gif'))
    show_frame(viewer, controller)
    assert image_info.texture_size == (10, 5)
    assert not image_info.needs_bigger_texture()
