from pathlib import Path

import dearpygui.dearpygui as dpg
from PIL import Image

import DearPyGui_ImageController as dpg_img

images_path = sorted((Path(__file__).parent / 'test_images').glob('*.*'))

dpg.create_context()
dpg_img.set_texture_registry(dpg.add_texture_registry(show=True))
dpg_img.default_controller.disable_work_in_threads = True

image_cell = dpg_img.ImageViewer()


def update_image(path):
    image = Image.open(path)
    image_cell.load(image)


with dpg.window() as window:
    if not images_path:
        dpg.add_text('Put some images into the test_images folder')
    with dpg.group(horizontal=True):
        for path in images_path:
            dpg.add_button(label=path.name, user_data=path, callback=lambda _, __, path: update_image(path))
    image_cell.create()

dpg.set_primary_window(window, True)
dpg.create_viewport()
dpg.setup_dearpygui()
dpg.show_viewport()
while dpg.is_dearpygui_running():
    dpg_img.default_controller.load_images(max_count=1)
    dpg_img.default_controller.unload_images(max_count=1)
    dpg_img.default_controller.animate()

    dpg.render_dearpygui_frame()
dpg.destroy_context()
