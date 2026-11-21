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


def test_animated_image_starts_animation_thread(tmp_path):
    path = (tmp_path / 'a.gif').as_posix()
    Image_ = __import__('PIL.Image', fromlist=['Image'])
    frames = [Image_.new('RGB', (4, 4), color) for color in ('red', 'blue')]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=50)
    assert count_threads(f'''
        import time
        with dpg.window():
            dpg_img.add_image({path!r})
        dpg.create_viewport()
        dpg.setup_dearpygui()
        dpg.show_viewport()
        end = time.time() + 1
        while time.time() < end:
            dpg.render_dearpygui_frame()
    ''') == 4


def test_enabling_threads_later_starts_them():
    assert count_threads('''
        controller = dpg_img.Controller(disable_work_in_threads=True)
        controller.add(Image.new('RGB', (4, 4)))
        controller.disable_work_in_threads = False
    ''') == 3


def test_threads_restart_after_disable_and_enable():
    assert count_threads('''
        import time
        dpg_img.default_controller.unloading_check_sleep_time = 0.05
        dpg_img.default_controller.add(Image.new('RGB', (4, 4)))
        dpg_img.default_controller.disable_work_in_threads = True
        time.sleep(0.3)
        dpg_img.default_controller.disable_work_in_threads = False
        time.sleep(0.1)
    ''') == 3


def test_failed_load_does_not_stop_the_loader():
    script = textwrap.dedent('''
        import time
        import dearpygui.dearpygui as dpg
        import DearPyGui_ImageController as dpg_img
        from DearPyGui_ImageController.controller import ImageController
        from PIL import Image
        dpg.create_context()
        dpg_img.set_texture_registry(dpg.add_texture_registry())
        controller = dpg_img.Controller(number_image_loader_workers=1)
        original = ImageController.is_unloading_time
        failed = []
        def fail_once(self):
            if not failed:
                failed.append(1)
                raise RuntimeError('simulated failure')
            return original(self)
        ImageController.is_unloading_time = fail_once
        with dpg.window(width=400, height=400):
            first = dpg_img.add_image(Image.new('RGB', (20, 20), 'red'), controller=controller)
            second = dpg_img.add_image(Image.new('RGB', (20, 20), 'blue'), controller=controller)
        dpg.create_viewport(); dpg.setup_dearpygui(); dpg.show_viewport()
        end = time.time() + 1.5
        while time.time() < end:
            dpg.render_dearpygui_frame()
        print(sorted(info.loaded for info in controller.values()))
        dpg.destroy_context()
    ''')
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
    assert 'simulated failure' in result.stderr
    assert result.stdout.strip().splitlines()[-1] == '[True, True]'


def test_disabled_before_first_image_starts_no_threads():
    assert count_threads('''
        dpg_img.default_controller.disable_work_in_threads = True
        dpg_img.default_controller.add(Image.new('RGB', (4, 4)))
    ''') == 0
