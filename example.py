import glob

import dearpygui.dearpygui as dpg

import DearPyGui_ImageController as dpg_img

dpg.create_context()
dpg_img.set_texture_registry(dpg.add_texture_registry(show=True))

all_image_viewers: list[dpg_img.ImageViewer] = []


def add_all_pictures():
    for i, file in enumerate(glob.glob("Test_images/*.*")):
        if not i % 8:
            group = dpg.add_group(horizontal=True, parent='picture_group')
        image_viewer = dpg_img.add_image(file, height=100, parent=group)  # noqa
        all_image_viewers.append(image_viewer)


def delete_all_pictures():
    for _ in range(len(all_image_viewers)):
        image_viewer = all_image_viewers.pop()
        image_viewer.delete()
    dpg.delete_item('picture_group', children_only=True)


def set_size():
    for image_viewer in all_image_viewers:
        image_viewer.set_size(width=50, height=50)


with dpg.window(label="Example Window", show=True, height=50, ):
    with dpg.group(horizontal=True):
        dpg.add_button(label='Set size', callback=set_size)
        dpg.add_button(label='Add all', callback=add_all_pictures)
        dpg.add_button(label='Delete all', callback=delete_all_pictures)

    with dpg.group(tag='picture_group'):
        pass

dpg.show_metrics()

dpg.create_viewport(title='Custom Title', width=1200, height=600)
dpg.setup_dearpygui()
dpg.show_viewport()
dpg.start_dearpygui()
dpg.destroy_context()
