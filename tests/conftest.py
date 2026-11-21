import dearpygui.dearpygui as dpg
import pytest

import DearPyGui_ImageController as dpg_img


@pytest.fixture
def controller():
    """A DPG context with a texture registry and a controller that loads only on demand."""
    dpg.create_context()
    dpg_img.set_texture_registry(dpg.add_texture_registry())
    dpg_img.tools.texture_plug = None
    controller = dpg_img.Controller(disable_work_in_threads=True)
    yield controller
    dpg.destroy_context()
