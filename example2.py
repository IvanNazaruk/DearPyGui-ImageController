import dearpygui.dearpygui as dpg
from PIL import Image

import DearPyGui_ImageController as dpg_img

dpg.create_context()
dpg_img.set_texture_registry(dpg.add_texture_registry(show=True))
dpg_img.default_controller.disable_work_in_threads = True

image_cell = dpg_img.ImageViewer()


def update_image(path):
    image = Image.open(path)
    image_cell.load(image)


with dpg.window() as window:
    dpg.add_button(label="1.jpg",
                   callback=lambda: update_image("1.jpg"))
    dpg.add_button(label="2.jpg",
                   callback=lambda: update_image("2.jpg"))
    image_cell.create()

dpg.set_primary_window(window, True)
dpg.create_viewport()
dpg.setup_dearpygui()
dpg.show_viewport()
while dpg.is_dearpygui_running():
    dpg_img.default_controller.load_images(max_count=1)
    dpg_img.default_controller.unload_images(max_count=1)

    dpg.render_dearpygui_frame()
dpg.destroy_context()
