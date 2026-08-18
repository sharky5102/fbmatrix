# FBMatrix: a HUB75 and WS281x driver library for Raspberry Pi 4 and 5

FBMatrix is a library and toolset to drive both HUB75 RGB matrix panels and ws2811 LED strings. FBMatrix first renders the target frame in memory and then drives the necessary outputs to render that frame on the LED device. All output signal processing is done by the V3D core in the raspberry pi, leaving the CPU free to do other things.

This requires the Raspberry Pi full KMS driver and its atomic DRM/KMS API. The
legacy framebuffer driver and FKMS (`vc4-fkms-v3d`) are not supported.

Right now, FBMatrix:
- Supports HUB75(e) RGB matrix displays up to 1920x32@60fps pixels with 12 BCM bitplanes
- Supports WS281x RGB strings, up to 14 strings of 2000 pixels, arbitrary positioning of the LEDs within a 2d field that the image is mapped to

### Features
- Utilizes GPU and V3D framebuffer to form 24 synchronized data streams with clock rate up to 100s of Mhz (but most HUB75 displays are limited to 30Mhz)
- Compatible with easy-to-obtain hardware (ADAFruit RGB bonnet), also for WS281x
- CPU usage relative to changes in the image; no change in image -> no CPU usage
- Rendering either by uploading RGB uint data, or by using OpenGL
- HUB75: supports 12-bit BCM, 1920x32 @ 60fps [using 25Mhz clock rate] with a single channel, currently only 1/16 scan with "standard" driver chips, but it is trivial to support 1/32 and others.
- WS281x: supports 24-bit color on up to 14 parallel strings of 2000 pixels
  each; the frame rate depends on the longest string
- WS281x: supports arbitrary pixel layout by providing a JSON file with pixel coordinates
- Provides fbmserve.py for selecting GLSL fragment shader effects from a browser.
- Audio port usable at the same time
- Gamma correction of 2.2 applied
- Provides simple fbmplay.py video player to play videos (including audio), which supports many videoformats due to the use of the ffpyplayer library. 
- Control for variable supersampling (averaging of input data "behind" an output pixel) and scaling of the output video.

[HUB75 demo on Adafruit 32x32 RGB matrix using Adafruit RGB matrix bonnet](https://www.youtube.com/watch?v=COhlBRFsR_o)

### Quick setup for HUB75 RGB matrices
**Assuming 1/16 scan RGB matrix**

This assumes a current Raspberry Pi OS installation with networking and SSH
configured. A text console is recommended because FBMatrix needs DRM master;
stop the display manager first if one is running.

1. Make sure you can access your Pi over the network via SSH. If SSH is not
   enabled, run:

		sudo raspi-config
		
	then select "Interfacing Options" and then "SSH"

2. Enable the KMS DPI output by adding the following to
   `/boot/firmware/config.txt`:

   ```ini
   [all]
   dtoverlay=vc4-kms-dpi-generic,rgb888
   ```

   This selects the full KMS driver. Do not use `vc4-fkms-v3d` or another FKMS
   overlay: FBMatrix requires atomic KMS modesetting. This is the only boot
   configuration FBMatrix requires. It creates the output mode itself at
   startup, so no framebuffer dimensions, DPI group/mode, or `dpi_timings`
   setting is needed.

3. Power off the pi, and attach the RGB bonnet and RGB display to the bonnet. Make sure the RGB matrix also has power.

4. Boot the pi. Once it has booted, ssh to it and run:

   ```bash
   sudo apt install python3-venv
   git clone https://github.com/sharky5102/fbmatrix.git
   cd fbmatrix
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```

   For HUB75 displays, you can now play a video:
   ```
   ./fbmplay some_video.mp4
   ```

   or, on ws2811, first generate a layout:
   ```
   ./generate-layout --rows 20 --columns 100 > layout.json
   ```

   and then play a video:

   ```
   ./fbmplay some_video.mp4 --display ws2811
   ```

   Activate the environment again in each new shell before running FBMatrix:

   ```bash
   source .venv/bin/activate
   ```

Presto! You should see a beautiful rendering of your video on your RGB matrix, with sound playing from the audio jack.

### Technical overview
FBMatrix works quite differently than other RGB driver libraries like the excellent rgbmatrix library. Instead of the CPU driving the GPIO pins in the correct order at the correct time, FBMatrix utilizes the DPI output driver of the video card on the Raspberry Pi4. 

The DPI driver is normally used to send digital data to LCD screens. It does this by scanning the video memory left-to-right, top-to-bottom and outputting each R, G and B value for a pixel at the same time to GPIO4-27 (24 bits, 8 bits Red, 8 bits Green, 8 bits Blue) at a rate selected by the dot clock of the video card (anywhere between 1 and a few hundred Mhz). This means that we effectively have 24 controllable digital output streams. WS2811 need only one stream, and HUB75E needs 14 streams. So that's easily enough!

This library crafts a specially prepared framebuffer based on the desired output data, which sets the correct bits of the R, G and B channels of the framebuffer, so that the GPIO pins go HIGH at just the right moment. The beauty of this method is that the DPI driver will keep driving the output, even when the CPU is idle. This means that once the output has been written to the framebuffer, the connected RGB matrix or ws281x string will continue to show the frame until the framebuffer is cleared or otherwise updated.

Finally, the framebuffer crafting is performed by the GPU by using OpenGL GLSL shaders. The GPU is particularly useful because calculating the value of each pixel's R, G and B values is inherently parellelizable, plus OpenGL gives us some nice tools to do Gamma correction and supersampling easily.

### HUB75(e) technical details
To use HUB75e, we use the following rendering method (assuming 1/16 scan RGB matrix):
- Each framebuffer scanline is 4096 pixels wide, and 16 (number of address lines) * 12 (bit depth) + 2 = 194 pixels high
- The dot clock is pulsed once every 2 pixels (on, off, on, off, on, off, etc) for the first 3840 pixels
- This gives us 3840/2 = 1920 bits of data. For each framebuffer scanline, we send 1920 bits of R, G and B bits for both the top half (R1G1B1) and bottom half (R2G2B2) of the picture
- The LAT (aka STB) signal is set HIGH directly after these 1920 pixels for about 10 pixels (the duration is not that important)
- OE signal is set HIGH for (4096 >> subframe) for each subframe of the line. This allows us to output the same line 12 times (on 12 different framebuffer scanlines), each for a BCM bitplane.
- Once all 12 bitplanes are output for one display line, we continue to the next by increasing the address line selector (which drives the A, B, C, D and E lines)
- The first line cannot be used to output OE, since no data is loaded, which increases the scanlines by one. The last line is used to zero out the shift registers on the display. This gives us the extra 2 framebuffer rows.

### Using WS281x output
FBMatrix also supports using WS281x "neopixel" LED strings. Currently, up to
2000 LEDs can be driven from each output pin. One way of physically
connecting the LED strings to your Pi is by using the RGB matrix bonnet, because it
contains a 3.3v to 5.0v level shifter for all the output pins. In that case
you simply connect data pins of the 16-pin cable (for example, the R1 pin) to
the data-in (Din) pins of your ws281x strings, and you'll have a
working setup.

You can also try to connect one of the GPIO outputs directly (eg GPIO4), but
that has 3.3v output levels so depending on your string, this may or may not
work.  My experience is that it works generally, but there is a lot of noise
and flickering on the output if you don't have a level shifter.

Here is an [example](https://www.youtube.com/watch?v=WgSfZ5cgZH4) of running
a video on a ws2811 string.

FBMatrix selects a width of 840 pixels and one active scanline per LED in the
longest string. For example, if the longest configured string has 200 LEDs,
the active KMS resolution is 840x200. A 50-line vertical sync interval provides
the WS281x reset gap between frames.

The outer array in `layout.json` contains the output strings, and each string
contains its LED positions in wire order. Strings can have different lengths,
but each is currently limited to 2000 LEDs. No padding is required. Up to 14
strings are supported.
An empty inner array leaves that output pin unused while retaining later string
numbers.

`generate-layout.py` groups generated LEDs into strings of 500 LEDs by default.
For radial layouts, a string contains only whole fixed sections, so
`--string-leds` must be a multiple of `--section-leds`. When it is omitted, the
generator uses the largest whole-section string up to the default 500 LEDs.
For example, `--section-leds 200 --string-leds 200` assigns one section to each
string and produces an active output resolution of 840x200.

The current WS281x universe-to-pin mapping is:

| String | Bonnet/HUB75 pin | Raspberry Pi GPIO |
| ------ | ---------------- | ----------------- |
| 0 | R1 | GPIO5 |
| 1 | G1 | GPIO13 |
| 2 | B1 | GPIO6 |
| 3 | R2 | GPIO12 |
| 4 | G2 | GPIO16 |
| 5 | B2 | GPIO23 |
| 6 | D | GPIO20 |
| 7 | LAT/STB | GPIO21 |
| 8 | A | GPIO22 |
| 9 | B | GPIO26 |
| 10 | C | GPIO27 |
| 11 | E | GPIO24 |
| 12 | OE | GPIO4 |
| 13 | CLK | GPIO17 |

Additionally, you will have to supply a layout to the renderer. The layout
lists the position in 3d space of each of your LEDs plus an integer source
mode. In most cases, your layout will have the LEDs in a flat surface, so the
z value (the third value of each pixel), will be 0.0. The source mode controls
where the LED color comes from:

- `-1`: inactive LED, always black
- `0`: sample the source framebuffer normally
- `1`: ignore the framebuffer and use red
- `2`: ignore the framebuffer and use green
- `3`: ignore the framebuffer and use blue

The command-line tools clear color source modes 1, 2 and 3 to 0 when loading a
layout, except for `fbmtest layout-colors`. Inactive source mode -1 is
preserved by all command-line tools, including `fbmtest`, `fbmplay` and
`fbmserve`. This lets one layout file contain diagnostic source modes for
testing while still marking bridge or spacer LEDs as always black during normal
playback.

Example contents for a 3-pixel ws281x string:

    [
      [ -1.0, 0.0, 0.0, 0 ],
      [  0.0, 0.0, 0.0, -1 ],
      [  1.0, 0.0, 0.0, 0 ]
    ]

As you can see, the values should be normalized to a (-1, 1) range. The file
above defines 3 LEDs, the first on the left, then one in the middle, and then
one on the right. Each pixel has an x, y, z and c parameter.

If you keep the layout in JSON, load it in your application and pass it to
the renderer explicitly:

    import json
    import fbmatrix

    with open('layout.json', 'rt') as f:
        layout = json.load(f)

    matrix = fbmatrix.renderer(display='ws2811', layout=layout)

If you have a perfect matrix (for example, you have a ws281x matrix on a
PCB), then you can use the generate-layout.py script to generate a
layout.json file:

    ./generate-layout.py square --columns 64 --rows 16 > layout.json

By default, the generated layout cycles row source modes through red, blue and
green for `fbmtest layout-colors`. Use `--source-modes framebuffer` to write
source mode 0 for every LED instead.

`generate-layout.py` can also generate a radial serpentine layout for physical
rectangles. Radial layouts divide the string into 8 fixed sections: two
balanced even spoke groups for each of the top-left, top-right, bottom-right
and bottom-left quarters. Each section is padded to `--section-leds` LEDs,
defaulting to 250. Padding LEDs and connector LEDs between spokes are written
with source mode `-1`, so they remain inactive during playback.

Physical radial layouts are normalized into the square `[-1, 1]` coordinate
space without changing aspect ratio. The larger physical dimension reaches the
square bounds; the smaller dimension is inset. For a 6 by 7 meter rectangle,
the y coordinates reach `-1` and `1`, while x coordinates are constrained to
about `-0.857` and `0.857`.

For example, this generates a 6 by 7 meter radial layout with 10cm LED spacing,
a 20cm central hub and 32 spokes:

    ./generate-layout.py radial --width 6 --height 7 --led-distance 0.1 --hub-radius 0.2 --spokes 32 --source-modes framebuffer > layout.json

The spoke count must be divisible by 8, so each quarter has an even number of
spokes. The generator splits each quarter into two even sections, such as 6/8
for a 14-spoke quarter, so every section starts and ends at the hub. The
generator calculates whether every section can fit in `--section-leds`; if not,
it exits with the section that needs more LEDs.

For radial and dual radial layouts, the generator also prints perimeter
crossings to stderr for harness construction. Crossings are physical distances
in meters along each edge: top and bottom are measured from the left edge, and
left and right are measured from the bottom edge.

For installations with two radial centers, `generate-layout.py` also supports
`dual-radial`. This layout assumes a portrait rectangle with two hubs on the
horizontal center line, separated by `--center-spacing`. The left and right
regions are semicircular fans with fixed angular spacing. The middle region is
filled by parallel vertical runs from the center line to the top and bottom
edges, using spacing derived from the adjacent radial edge spacing.

Dual radial layouts are split into four symmetric physical parts: top-left,
top-right, bottom-right and bottom-left. Each part contains two fixed LED
sections, so the generated layout has 8 sections total. Each section is padded
to `--section-leds` LEDs, defaulting to 250. A section may continue from side
fan runs into parallel center runs, and every section starts and ends either at
a hub or on the center line. Connector and padding LEDs use source mode `-1`.

For example, this generates a 4 by 5 meter dual radial layout with two hubs
1.6 meters apart:

    ./generate-layout.py dual-radial --width 4 --height 5 --led-distance 0.1 --hub-radius 0.2 --spokes 32 --center-spacing 1.6 --source-modes framebuffer > layout.json

The dual radial spoke count is the total number of radial spokes across both
semicircular regions and must be divisible by 4. When `--center-spacing 0` is
used, `dual-radial` collapses to the normal `radial` generator and uses its
divisible-by-8 spoke requirement.

Use `--max-spoke-length` to cap LED-bearing run length in meters. This clips
long spokes before placing LEDs, which is useful for trimming rectangle corners
when a section would otherwise exceed `--section-leds`. For example, this keeps
the longest runs in the 6 by 7 meter dual radial layout below 2.8 meters:

    ./generate-layout.py dual-radial --width 6 --height 7 --led-distance 0.1 --hub-radius 0.2 --spokes 52 --center-spacing 1.5 --max-spoke-length 2.8 --source-modes framebuffer > layout.json

To play a video, use the same procedure as for HUB75 to play a video, except
add the --display parameter:

    ./fbmplay --display ws2811 video.mp4

### Serving shader effects

`fbmserve.py` runs the normal FBMatrix renderer and starts a small HTTP server
for selecting GLSL fragment shader effects with a live WebGL2 preview:

    ./fbmserve.py --emulate --port 8080

Add `--autoplay --autoplay-interval 20` to switch randomly between effects
every 20 seconds. Autoplay is handled server-side, so it continues even when
the browser UI is closed.

`fbmserve.py` renders effects into a 4x source framebuffer by default before
sampling them down to the LEDs. Use `--source-scale`, `--source-columns` or
`--source-rows` to tune the source resolution. For WS2811 layouts, the default
source framebuffer follows the physical aspect ratio of the active LED bounds.
Those bounds are normalized to the complete source texture for sampling, while
the original layout coordinates remain unchanged for geometry and emulation.
Its native resolution is estimated from typical active-LED spacing, then
multiplied by `--source-scale`. Exact `--source-columns` and `--source-rows`
overrides are reserved for HUB75 and are rejected for WS2811.

The browser UI is served from `web/`, and effects are loaded from `effects/`.

### NDI input

`fbmserve.py` can optionally discover and receive NDI video using the native NDI
runtime through CFFI. The NDI SDK library is not included. Point fbmatrix at an
installed NDI 6 runtime, then select NDI and a discovered source in the web UI:

    FBMATRIX_NDI_LIBRARY="/home/pi/NDI SDK for Linux/lib/aarch64-rpi4-linux-gnueabi/libndi.so" ./fbmserve.py

If the variable is unset or the library cannot be loaded, effects continue to
work and the UI reports NDI as unavailable when selected. Discovery refreshes
periodically and preserves the selected source while it is offline.
Effects use a Shadertoy-style fragment entry point:

    void mainImage(out vec4 fragColor, in vec2 fragCoord)

The renderer provides `iTime`, `iResolution`, `iHue` and `iBrightness`
uniforms. The usual output flags such as `--display`, `--layout`, `--emulate`,
`--preview` and `--raw` are shared with `fbmtest.py` and `fbmplay.py`.
