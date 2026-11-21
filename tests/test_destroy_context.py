import subprocess
import sys
import textwrap

import pytest
from PIL import Image

SETUP = '''
import time
import dearpygui.dearpygui as dpg
import DearPyGui_ImageController as dpg_img
from PIL import Image
dpg.create_context()
dpg_img.set_texture_registry(dpg.add_texture_registry())
dpg.create_viewport(); dpg.setup_dearpygui(); dpg.show_viewport()
def run(seconds):
    end = time.time() + seconds
    while time.time() < end:
        dpg.render_dearpygui_frame()
'''


def run_script(code):
    """The scenario runs in a fresh interpreter: a crash ends the process with a non-zero exit code."""
    result = subprocess.run([sys.executable, '-c', SETUP + textwrap.dedent(code)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout


@pytest.fixture
def gif_path(tmp_path):
    frames = [Image.new('RGB', (40, 40), color) for color in ('red', 'green', 'blue')]
    frames[0].save(tmp_path / 'a.gif', save_all=True, append_images=frames[1:], duration=20, loop=0)
    return (tmp_path / 'a.gif').as_posix()


def test_animation_thread_after_destroy_context(gif_path):
    run_script(f'''
        with dpg.window():
            dpg_img.add_image({gif_path!r})
        run(1)
        dpg.destroy_context()
        time.sleep(0.5)
    ''')


def test_handler_deleter_after_destroy_context():
    run_script('''
        with dpg.window():
            viewer = dpg_img.add_image(Image.new('RGB', (40, 40)))
        run(0.5)
        viewer.delete()
        dpg.destroy_context()
        time.sleep(0.5)
    ''')


def test_unloader_after_destroy_context():
    run_script('''
        dpg_img.default_controller.max_inactive_time = 0.1
        dpg_img.default_controller.unloading_check_sleep_time = 0.05
        with dpg.window() as window:
            dpg_img.add_image(Image.new('RGB', (40, 40)))
        run(0.5)
        dpg.configure_item(window, show=False)
        dpg.destroy_context()
        time.sleep(0.5)
    ''')


def test_new_context_after_destroy_works():
    output = run_script('''
        dpg.destroy_context()
        dpg.create_context()
        dpg_img.tools.texture_plug = None
        dpg_img.set_texture_registry(dpg.add_texture_registry())
        dpg.create_viewport(); dpg.setup_dearpygui(); dpg.show_viewport()
        with dpg.window():
            dpg_img.add_image(Image.new('RGB', (40, 40)))
        run(1)
        print([info.loaded for info in dpg_img.default_controller.values()])
        dpg.destroy_context()
    ''')
    assert output.strip().splitlines()[-1] == '[True]'
