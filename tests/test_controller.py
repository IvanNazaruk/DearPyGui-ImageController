from PIL import Image


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
