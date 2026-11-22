## DearPyGui-ImageController
Shows a lot of images in [Dear PyGui](https://github.com/hoffstadt/DearPyGui) without running out of memory.

An image is loaded into DPG only while it is visible. If it stays out of sight for a while, its texture is unloaded and loaded again when it comes back into view.

**Features**
- Loads visible images in background threads and unloads hidden ones
- Textures are created at the size the image is shown, not at the full image size
- Optional memory limit per image
- Animated GIF, APNG and WebP
- Blurred preview while an image is loading
- The same image added several times is loaded once

## Demo video

https://user-images.githubusercontent.com/46572469/208324280-9e2e02a1-0479-433c-82ac-9fd1fdf7f13c.mp4

*1255 images with 1920×1080 resolution were used. The video shows an older version: without the blurred preview, view-sized textures and animations.*

You can try this example with [example.py](example.py) (put images into a `test_images` folder next to it).

## Installation
Python 3.10 or newer.
```shell
pip install "DearPyGui-ImageController[numpy]"
```
`[numpy]` also installs numpy: without it, images load about 8 times slower. Without numpy: `pip install DearPyGui-ImageController`.

The latest development version: `pip install git+https://github.com/IvanNazaruk/DearPyGui-ImageController`

## Quick start
```python
import dearpygui.dearpygui as dpg

import DearPyGui_ImageController as dpg_img

dpg.create_context()
dpg_img.set_texture_registry(dpg.add_texture_registry())

with dpg.window():
    dpg_img.add_image("{IMAGE_PATH}")

    # Or a Pillow image:
    # from PIL import Image
    # dpg_img.add_image(Image.open("{IMAGE_PATH}"))

dpg.create_viewport()
dpg.setup_dearpygui()
dpg.show_viewport()
dpg.start_dearpygui()
dpg.destroy_context()
```
`add_image` accepts a path, bytes, a file object or a Pillow `Image`, and returns an `ImageViewer`.

## Image viewer
`add_image(image, width=None, height=None, parent=0, controller=None, show_loading_indicator=False)` creates an `ImageViewer`. You can also create one yourself and change its image later:
```python
viewer = dpg_img.ImageViewer()
viewer.create(parent=window)       # adds it to DPG
viewer.load("{IMAGE_PATH}")        # shows another image
viewer.unload()                    # shows nothing
viewer.delete()                    # removes it from DPG
```

### Size
Use `set_width`, `set_height` and `set_size`. If only one dimension is set, the other one follows the image proportions. If neither is set, the image size is used.
```python
viewer = dpg_img.add_image("{IMAGE_PATH}", height=100)
viewer.set_size(width=50, height=50)
```
The texture is created at the size the image is shown, not at the file size. A 1920×1080 photo shown 120 px wide gets a 120×67 texture: about 0.13 MB instead of 33 MB.

- **The viewer grows**: the texture is rebuilt with 1.5× headroom (never bigger than the image), so resizing step by step, e.g. with a slider, doesn't rebuild it on every step.
- **The size settles**: once the viewer size hasn't changed for `shrink_delay` seconds (10 by default), a texture that is noticeably bigger than needed is rebuilt at the exact size. This drops the 1.5× headroom after growing and frees memory after the viewer shrank.
- **No size set**: a viewer without `width`/`height` shows the image at its real size, so it gets the full-size texture.

### Click and other handlers
Use `set_image_handler`; it works even while the image is not loaded:
```python
with dpg.item_handler_registry() as image_handler:
    dpg.add_item_clicked_handler(callback=lambda _, data: print(f"Clicked: {data[0]}"))

image_viewer = dpg_img.add_image("{IMAGE_PATH}")
image_viewer.set_image_handler(image_handler)
```

### Blurred preview while loading
Until the real texture is loaded, the viewer shows a tiny 16 px wide copy of the image stretched to the viewer size. It costs about 4 KB of texture memory per image. To also show a loading indicator over it, pass `show_loading_indicator=True` to `add_image` or `ImageViewer`.

## Animations
GIF, APNG and animated WebP play automatically while they are visible and pause when they are not. Frames follow the durations stored in the file, by time, not by rendered frames. Every frame is a separate texture, so an animation takes as many times more memory as it has frames; `max_texture_bytes` (below) caps it.

## Controller settings
All viewers use `dpg_img.default_controller` unless you pass your own `dpg_img.Controller(...)` with `controller=`. Settings:

| Setting                       | Default | What it does                                                                                      |
| ----------------------------- | ------- | ------------------------------------------------------------------------------------------------- |
| `max_inactive_time`           | `10`    | Seconds an image can stay out of sight before it is unloaded                                      |
| `unloading_check_sleep_time`  | `2.5`   | How often (seconds) hidden images are checked for unloading                                       |
| `number_image_loader_workers` | `2`     | Images loaded at the same time (constructor only)                                                 |
| `max_texture_bytes`           | `None`  | Texture memory limit for one image, all frames together; bigger images load at a lower resolution |
| `preview_size`                | `16`    | Width of the blurred preview in pixels; `0` turns it off                                          |
| `shrink_delay`                | `10`    | Seconds the viewer size must stay the same before an oversized texture is rebuilt smaller; `None` turns it off |
| `disable_work_in_threads`     | `False` | Load, unload and animate in your own loop instead of threads                                      |

DPG stores every texture pixel as 4 floats (16 bytes), so a 1920×1080 picture takes about 33 MB:
```python
dpg_img.default_controller.max_texture_bytes = 16 * 1024 * 1024  # 16 MB per image
```

### Without threads
With `disable_work_in_threads = True` no threads are started, and your render loop does the work:
```python
dpg_img.default_controller.disable_work_in_threads = True
...
while dpg.is_dearpygui_running():
    dpg_img.default_controller.load_images(max_count=1)
    dpg_img.default_controller.unload_images(max_count=1)
    dpg_img.default_controller.animate()
    dpg.render_dearpygui_frame()
```
Full example: [example2.py](example2.py).

## Closing the app
Nothing special: call `dpg.destroy_context()` as usual.

The library loads, unloads and animates images in background threads, and any DPG call after the context is destroyed crashes the whole process (segfault). So on import the library decorates `dpg.destroy_context`: before destroying the context it waits until these threads finish their current DPG call (up to about a second while a big animation is loading) and stops them from calling DPG. A new context works again after `dpg_img.set_texture_registry(...)`, as usual.

This works when you call it as `dpg.destroy_context()`. If you imported the function itself before the library (`from dearpygui.dearpygui import destroy_context`), that name points to the undecorated function.

## Development
```shell
pip install -r requirements-dev.txt
python -m pytest
```
