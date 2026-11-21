import gc
import os
import sys

import dearpygui.dearpygui as dpg
import pytest

import DearPyGui_ImageController as dpg_img


def pytest_collection_modifyitems(items):
    if sys.platform.startswith('linux') and not os.environ.get('DISPLAY'):
        skip = pytest.mark.skip(reason='needs a display: run with xvfb-run')
        for item in items:
            if 'display' in item.keywords:
                item.add_marker(skip)


@pytest.fixture
def controller():
    """A DPG context with a texture registry and a controller that loads only on demand."""
    dpg.create_context()
    dpg_img.set_texture_registry(dpg.add_texture_registry())
    dpg_img.tools.texture_plug = None
    dpg_img.ImageViewer._get_theme.__func__.cache_clear()  # the cached theme belongs to the previous context
    controller = dpg_img.Controller(disable_work_in_threads=True)
    yield controller
    # Viewers call DPG in __del__, so delete them while the context still exists
    for image_info in list(controller.values()):
        for viewer in list(image_info.subscribers.values()):
            viewer.delete()
    gc.collect()
    dpg.destroy_context()
