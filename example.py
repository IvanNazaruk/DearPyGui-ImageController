import glob
import traceback
from typing import List

import dearpygui.dearpygui as dpg

import DearPyGui_ImageController as dpg_img

path_to_images = "test_images"
images_path = glob.glob(f"{path_to_images}/*.*")

dpg.create_context()

dpg_img.set_texture_registry(dpg.add_texture_registry(show=True))
dpg_img.default_controller.max_inactive_time = 10
dpg_img.default_controller.unloading_check_sleep_time = 2.5

all_image_viewers: List[dpg_img.ImageViewer] = []


def add_all_images():
    for i, file in enumerate(images_path):
        if not i % 8:
            group = dpg.add_group(horizontal=True, parent=image_group)
        image_viewer = dpg_img.add_image(file, height=100, parent=group)  # noqa
        all_image_viewers.append(image_viewer)


def delete_all_images():
    for _ in range(len(all_image_viewers)):
        image_viewer = all_image_viewers.pop()
        image_viewer.delete()
    dpg.delete_item(image_group, children_only=True)


def set_size():
    for image_viewer in all_image_viewers:
        image_viewer.set_size(width=50, height=50)


image_viewer = dpg_img.ImageViewer(unload_width=1, unload_height=1)


def load_image(path):
    if path == "{None}":
        image_viewer.unload()
        dpg.set_value(image_info, path)
        return

    try:
        image_viewer.load(path, dpg.get_value(show_load_checkbox))
        dpg.set_value(image_info, f"{image_viewer.image.width}x{image_viewer.image.height} | {path}")
    except Exception as e:
        traceback.print_exc()
        image_viewer.unload()
        dpg.set_value(image_info, f"{str(e)}")


def update_size(self):
    width, height = dpg.get_value(image_width), dpg.get_value(image_height)
    width_max, height_max = dpg.get_item_configuration(image_width)['max_value'], dpg.get_item_configuration(image_height)['max_value']
    if width <= 0 or width > width_max:
        width = None
    if height <= 0 or height > height_max:
        height = None
    dpg.set_value(now_size, f"{width}x{height}")
    image_viewer.set_size(width=width, height=height)


with dpg.window(label="Example Window", height=400, width=500):
    with dpg.tab_bar():
        with dpg.tab(label='Example "gallery"'):
            with dpg.group(horizontal=True):
                dpg.add_button(label="Set size (50x50)", callback=set_size)
                dpg.add_button(label="Add all", callback=add_all_images)
                dpg.add_button(label="Delete all", callback=delete_all_images)
            with dpg.group() as image_group:
                pass

        with dpg.tab(label='Example "viewer"'):
            dpg.add_combo(["{None}"] + images_path, callback=lambda _, path: load_image(path))
            show_load_checkbox = dpg.add_checkbox(label='Show loading')
            image_info = dpg.add_text("{None}")
            with dpg.group(horizontal=True):
                dpg.add_text("Width:")
                image_width = dpg.add_input_int(min_value=0, max_value=100_000, step=0)
            with dpg.group(horizontal=True):
                dpg.add_text("Height:")
                image_height = dpg.add_input_int(min_value=0, max_value=100_000, step=0)
            with dpg.group(horizontal=True):
                dpg.add_button(label="Update size", callback=update_size)
                now_size = dpg.add_text("NonexNone")
            image_viewer.create()

dpg.show_metrics()

dpg.create_viewport(title='DearPyGui-ImageController', width=1200, height=600)
dpg.setup_dearpygui()
dpg.show_viewport()
dpg.start_dearpygui()
dpg.destroy_context()
