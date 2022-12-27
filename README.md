## DearPyGui-ImageController
Optimizes RAM consumption by unloading images from the DPG.

It works quite simply: if the image is visible it is loaded, if not visible then after a certain amount of time is unloaded from the DPG
## Demo video

https://user-images.githubusercontent.com/46572469/208324280-9e2e02a1-0479-433c-82ac-9fd1fdf7f13c.mp4

*1255 images with 1920×1080 resolution were used*

#### You can try this example using this script: [example.py](example.py)


## How to use it?
0) Download the library(`git clone https://github.com/IvanNazaruk/DearPyGui-ImageController`) and move the `DearPyGui_ImageController` folder to your project/script

1) Import the library:
```python
import DearPyGui_ImageController as dpg_img
```
2) Set DPG texture registry:
```python
dpg_img.set_texture_registry(dpg.add_texture_registry())
```
3) Add the image:
```python
dpg_img.add_image("{IMAGE_PATH}")
```
Or use Pillow:
```python
from PIL import Image
img = Image.open("{IMAGE_PATH}")
dpg_img.add_image(img)
```

### Full example:
```python
import dearpygui.dearpygui as dpg

import DearPyGui_ImageController as dpg_img

dpg.create_context()
dpg_img.set_texture_registry(dpg.add_texture_registry())

with dpg.window():
    dpg_img.add_image("{IMAGE_PATH}")

    # from PIL import Image
    # img = Image.open("{IMAGE_PATH}")
    # dpg_img.add_image(img)

dpg.create_viewport()
dpg.setup_dearpygui()
dpg.show_viewport()
dpg.start_dearpygui()
dpg.destroy_context()
```

## Additional Information
 - ### How to resize an image after it has been created?
 
 Use the internal functions `set_width`, `set_height` and `set_size`. If width or height is not specified, the other dimension will be decreased/increased proportionally. If the dimensions are not set, the image size will be used.
 
 An example use case is found in [example.py](example.py):<br/>
 First we will save the created image viewer object:
 https://github.com/IvanNazaruk/DearPyGui-ImageController/blob/5866e1ddbd84a4cd5252a092627841df2d42a32c/example.py#L21-L22
 And after that they are resized:
 https://github.com/IvanNazaruk/DearPyGui-ImageController/blob/5866e1ddbd84a4cd5252a092627841df2d42a32c/example.py#L33-L34

 - ### How do I bind the DPG handler to the image?
 Use the internal function `set_image_handler`. Example usage:
```python
with dpg.item_handler_registry() as image_handler:
    dpg.add_item_clicked_handler(callback=lambda _, data: print(f"Clicked: {data[0]}"))

image_viewer = dpg_img.add_image("{IMAGE_PATH}")
image_viewer.set_image_handler(image_handler)
```
 
 ## TODO list
 - [ ] Increase documentation
 - [ ] GIFs support
 
