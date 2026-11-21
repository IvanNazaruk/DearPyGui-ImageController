import subprocess
import sys
import textwrap

import dearpygui.dearpygui as dpg
import pytest

from DearPyGui_ImageController.tools import HandlerDeleter


def test_deletes_right_away_without_render_loop(controller):
    handler = dpg.add_item_handler_registry()
    HandlerDeleter.add(handler)
    assert not dpg.does_item_exist(handler)


@pytest.mark.display
def test_deletes_after_delay_frames_in_render_loop():
    """In a fresh interpreter: the render loop needs a viewport."""
    script = textwrap.dedent('''
        import time
        import dearpygui.dearpygui as dpg
        import DearPyGui_ImageController as dpg_img
        from DearPyGui_ImageController.tools import HandlerDeleter
        dpg.create_context()
        dpg.create_viewport(); dpg.setup_dearpygui(); dpg.show_viewport()
        dpg.render_dearpygui_frame()
        handler = dpg.add_item_handler_registry()
        HandlerDeleter.add(handler)
        start = dpg.get_frame_count()
        while dpg.does_item_exist(handler) and dpg.get_frame_count() - start < 500:
            dpg.render_dearpygui_frame()
        frames = dpg.get_frame_count() - start
        for _ in range(10):
            dpg.render_dearpygui_frame(); time.sleep(0.01)
        print(frames, HandlerDeleter._thread_running)
        dpg.destroy_context()
    ''')
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, check=True)
    frames, thread_running = result.stdout.split()
    assert HandlerDeleter.delay_frames <= int(frames) < 500
    assert thread_running == 'False'
