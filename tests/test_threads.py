import subprocess
import sys
import textwrap


def count_threads(code):
    """Runs code in a fresh interpreter (this one has already imported the library) and returns its output."""
    script = textwrap.dedent('''
        import threading
        import dearpygui.dearpygui as dpg
        import DearPyGui_ImageController as dpg_img
        from PIL import Image
        dpg.create_context()
        dpg_img.set_texture_registry(dpg.add_texture_registry())
        before = threading.active_count()
    ''') + textwrap.dedent(code) + "\nprint(threading.active_count() - before)"
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, check=True)
    return int(result.stdout.strip().splitlines()[-1])


def test_import_starts_no_threads():
    assert count_threads('') == 0


def test_first_image_starts_threads():
    assert count_threads("dpg_img.default_controller.add(Image.new('RGB', (4, 4)))") == 3


def test_disabled_before_first_image_starts_no_threads():
    assert count_threads('''
        dpg_img.default_controller.disable_work_in_threads = True
        dpg_img.default_controller.add(Image.new('RGB', (4, 4)))
    ''') == 0
