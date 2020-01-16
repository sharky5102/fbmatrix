# FBMatrix: an RGB display library for Raspberry Pi 4

### Features

- Supports HUB75(e) RGB matrix displays
- Supports WS281x RGB strings arranged as a display
- Utilizes GPU and V3D framebuffer to form 24 synchronized data streams with clock rate up to 100s of Mhz (but most HUB75 displays are limited to 30Mhz)
- Compatible with easy-to-obtain hardware (ADAFruit RGB bonnet)
- CPU usage relative to changes in the image; no change in image -> no CPU usage
- Rendering either by uploading RGB uint data, or by using OpenGL
- HUB75: supports 12-bit BCM, 1920x32 @ 60fps [using 25Mhz clock rate] with a single channel, currently only 1/16 scan with "standard" driver chips, but it is trivial to support 1/32 and others.
- WS281x: supports 8-bit PWM, 1024 pixels @ 60fps [800Kbit mode].
- WS281x: supports arbitrary pixel layout by providing a JSON file with pixel coordinates
- Audio port usable at the same time
- Gamma correction of 2.2 applied
- Provides simple fbmplay.py video player to play videos (including audio), which supports many videoformats due to the use of the ffpyplayer library. It has control for variable supersampling (averaging of input data "behind" an output pixel) and scaling of the output video.

### Quick setup for HUB75 RGB matrices
**Assuming 1/16 scan RGB matrix**

This assumes a clean NOOBS install. It should be booting into X-Windows (not a command prompt)

1. Make sure you can access your pi over the network via SSH. You will not be able to use the HDMI port together with FBMatrix (although I think it is possible, just haven't spent to time to find the right configuration). If you can't access your pi via ssh, you can set it up using

		sudo raspi-config
		
	then select "Interfacing Options" and then "SSH"

2. You need to enable the DPI display output on your Raspberry pi, by adding the following to your /boot/config.txt:

		dtoverlay=dpi24
		overscan_left=0
		overscan_right=0
		overscan_top=0
		overscan_bottom=0
		framebuffer_width=4096
		framebuffer_height=194
		enable_dpi_lcd=1
		display_default_lcd=1
		dpi_group=2
		dpi_mode=87
		dpi_output_format=0x6f007
		dpi_timings=4096 0 0 0 0 194 0 0 0 0 0 0 0 60 0 50000000 6

3. Power off the pi, and attach the RGB bonnet and RGB display to the bonnet. Make sure the RGB matrix also has power.

4. Boot the pi. While it boots, your LED matrix will start to display some junk. This is because it is interpreting the boot sequence output by DPI as a data signal. Just ignore it. 

5. Once the pi has booted, ssh to your pi, and run:

		pip3 install pipenv
		git clone https://github.com/sharky5102/fbmatrix.git
		cd fbmatrix
		pipenv shell
		export DISPLAY=:0
		./fbmplay some_video.mp4

Presto! You should see a beautiful rendering of your video on your RGB matrix, with sound playing from the audio jack.

*If someone is interested, I think we should be able to run with HDMI enabled for your *actual* monitor, and the second "monitor" providing the DPI output. This would also fix the junk display output during boot.*

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
