from PIL import Image

from DearPyGui_ImageController.controller import ImageUnloaderWorker


def test_different_solid_images_are_not_merged(controller):
    white_tag, _ = controller.add(Image.new('RGB', (64, 64), 'white'))
    black_tag, black_info = controller.add(Image.new('RGB', (64, 64), 'black'))
    assert white_tag != black_tag
    assert black_info.image.getpixel((0, 0)) == (0, 0, 0)


def test_same_file_is_merged(controller, tmp_path):
    path = tmp_path / 'image.png'
    Image.new('RGB', (10, 10), 'red').save(path)
    assert controller.add(path)[0] == controller.add(path)[0]


def test_same_bytes_with_different_size_are_not_merged(controller):
    data = bytes(range(16)) * 3
    assert controller.add(Image.frombytes('RGB', (2, 8), data))[0] != controller.add(Image.frombytes('RGB', (4, 4), data))[0]


def add_expired_images(controller, count):
    for color in range(count):
        _, image_info = controller.add(Image.new('RGB', (4, 4), (color, 0, 0)))
        controller.unload_queue.append(image_info)  # last_time_visible = 0, so already expired


def test_unload_images_unloads_every_expired_image(controller):
    add_expired_images(controller, 4)
    controller._last_time_unload_check = 0
    controller.unload_images()
    assert controller.unload_queue == []


def test_unloader_worker_unloads_every_expired_image(controller, monkeypatch):
    add_expired_images(controller, 4)
    monkeypatch.setattr('time.sleep', lambda seconds: None)
    ImageUnloaderWorker.loop(controller.unloading_worker)
    assert controller.unload_queue == []
