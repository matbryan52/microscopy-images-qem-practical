# QEM 2025 Image Processing Practical Session

Describes the practical session for QEM2025 related to image processing using HyperSpy and Python.

## Setup

### Juypter interactive figures

To have HyperSpy figures be interactive, add the following to a cell at the top of your notebook and run it:

```python
%matplotlib widget
```

## Objective

The objective is to carry out STEM imaging measurements (radius, area etc.) of a sample of gold nanoparticles using a simulated microscope. The simulated microscope in its default state has a drifting stage, so we cannot use the survey image to identify where to run a high-resolution scan, because the particle will move outside the field of view by the time we scan it.

## Exercises

In order of increasing difficulty...

> **NOTE**: Below the exercises is an explanation of how to work with the simulator and HyperSpy, [CLICK HERE](#simulator).

### 1 - Detect, image and measure particles without drift

Create the simulator with no drift using:

```python
from qem_practical.simulator import STEMImageSimulator

simulator = STEMImageSimulator.default(drift_speed=0.)
```
This means we can treat the survey image as *static* and measure any particle within the field of view without distortion or tracking.

1. From a survey image taken at a good dwell time (`1e-5` s) **locate most of the particles** in the field of view using a peak-finding approach
  - HyperSpy provides a method `signal.find_peaks()`, documented [here](https://hyperspy.org/hyperspy-doc/current/reference/api.signals/Signal2D.html#hyperspy.api.signals.Signal2D.find_peaks).
    - Give the argument `interactive=False` to avoid showing the UI in the Jupyter Notebook
    - You will need to limit the number of peaks returned, use `min_distance=35` or more as an extra argument.
    - Setting `current_index=True` will give a single result, and the peaks positions are then at `peaks.data`.
    - The peaks are returned as `[pixel_y, pixel_x]` positions, in a `(n_peaks, 2)` shaped array
2. For some of the detected particles run a STEM `simulator.scan()` of each and display a few of the images
  - `simulator.scan` takes nano-metre coordinates for the centre of the scan grid. You can convert from pixel peak positions to nanometre coordinates with `centre = simulator.survey.to_continuous((pixel_y, pixel_x))`.
  - To avoid displaying the progress bar many times set `progress=False` in the call to `simulator.scan()`
3. For each scan image apply a **threshold** in intensity to the numpy array to segment the particle from the background
  - The numpy array of an HyperSpy signal is always at `signal.data`
  - A numpy array can be thresholded directly by comparing it to a value, e.g. `threshold_image = scan_image.data > 50`.
  - If your thresholded image contains artefacts (small dots or holes), either increase your dwell time, change the threshold or consider using:
    ```python
    from skimage.morphology import remove_small_objects
    numpy_array = remove_small_objects(numpy_array, min_size=8)  # delete regions larger than 8px in size
    ```
4. For each segmented image of a particle **measure the particle** properties (e.g. diameter, circumference, area, circularity).
  - The function [`skimage.measure.regionprops`](https://scikit-image.org/docs/stable/api/skimage.measure.html#skimage.measure.regionprops) measures many particle properties.
  - It cannot operate on a boolean image directly, but you can convert one into an integer image with `threshold_image.astype(int)`.
  - `regionprops` will return a `list` of property objects, one-per-particle in the image. If you only have one particle access this with `properties[0]`
  - Try to use `regionprops` to express the measurements in *nanometres* rather than pixels, based on the information you have about each scan.
5. Plot the distributions of some of the property values as histograms (using `plt.hist`).
  - Property values are found by name (as given in the documentation), e.g. `properties[0].area`.

### 2 - Estimate the drift and correct an image stack

Create a simulator with a random drift speed `drift_speed="random"`. The survey image will now change over time as particles move through the field of view. The drift rate will be approximately constant while the drift direction slowly changes over time.

1. Create a survey image with a short dwell time (`1e-6` s)
2. Identify or choose a small area of particles to scan
3. Create an image stack of this area at a higher resolution (lower `scan_step`)
  - A stack scan can be run with `simulator.scan(..., stack=8)` to acquire an 8-image stack.
4. Estimate the drift vector between successive frames
  - HyperSpy provides a function `signal.estimate_shift2D()` to do this on a stack (see [here](https://hyperspy.org/hyperspy-doc/current/reference/api.signals/Signal2D.html#hyperspy.api.signals.Signal2D.estimate_shift2D)).
5. Plot the drift over time and compare it to the simulator's true drift curve which can accessed with:

```python
# drift_dataframe contains columns "timestamp", "yvals", "xvals" in nanometres
timestamps = stack.axes_manager["time"].axis
drift_dataframe = simulator.drift_for_time(timestamps)
```

6. Drift-correct the acquired stack
  - HyperSpy provides a function `signal.align2D()` to do this on a stack (see [here](https://hyperspy.org/hyperspy-doc/current/reference/api.signals/Signal2D.html#hyperspy.api.signals.Signal2D.align2D)).
7. Display the sum of the corrected and original stacks to compare the results of drift correction

### 3 - Live drift correction

Since we can estimate the drift curve based on past images then we can also shift the scan grid predictively to compensate future drift. In the simulator we can supply a function `drift_corrector` which takes the timestamp of the scan about to start, and shifts the supplied `centre` of the scan grid by some amount. A simple function to do this would be:

```python
def predict_drift(scan_time: float) -> tuple[float, float]:
    return (1. * scan_time, -0.3 * scan_time)
```

which would move the supplied scan `centre` coordinate by `(1, -0.3)` nm for every second since the simulator was created.

Such a function would need to be created from a sequence of drift-measurement acquisitions, then applied to a new scan. The function would be less and less valid over time as the drift of the sample is not stable. The correction function would therefore need to be re-measured periodically.

1. Acquire a survey image and select a zone to track
2. **Acquire a stack** of images of the tracking region
3. Evaluate the drift as in exercise 2, then **fit a function** to predict it as a function of scan time
  - The `"time"` axis of a stack acquisition is calibrated to scan time, accessed with `stack.axes_manager["time"].axis`
  - The function must return an *offset* to apply to the scan `centre` coordinate, so fit drift relative to the content in the first image of the stack.
  - Over short time periods, a linear fit to the drift is sufficient.
4. Supply the `drift_corrector` function to a new stack acquisition on the same or a new area
5. Plot the results to prove the drift correction is working
  - Sum an uncorrected stack and a corrected stack to see if the detail improves
6. Based on the new stack, **update** your drift correction function with the new images
  - The centre points of each image in the stack are at `image.metadata.corrected_centre`
  - The correction value applied for each image is at `image.metadata.correction`.

## Simulator examples

> **NOTE:** This section demonstrates some features of the simulator The numbers in the examples are arbitrary and will not correspond to the images in this section if you run them yourself.

The simulator reproduces ADF-STEM imaging on a sample of nanoparticles which are drifting through the field of view. The simulator can be created like so:

```python
from qem_practical.simulator import STEMImageSimulator

simulator = STEMImageSimulator.default()
```

The `default()` method can be called with `drift_speed=0.` to completely disable drifting, as needed in exercise 1.

The simulator object has two primary user-facing methods, one to acquire a survey image over a fixed, wide field of view at a large scan stepsize:

```python
survey_image = simulator.survey_image(dwell_time=1e-6)  # seconds
```

where `survey_image` is a `512x512` [HyperSpy](https://hyperspy.org/hyperspy-doc/current/user_guide/index.html)
`Signal2D`.

![image](./survey-image.png)

The simulator can also acquire a detailed STEM scan of a given field of view, shape and scan stepsize:

```python
scan_image = simulator.scan(
    centre=(61.3, 34.2),  # (y, x) centre of the scan grid in the coordinate system of the survey image, in NanoMetres
    scan_shape=(100, 180),  # (y, x) scan grid shape (integer)
    scan_step=0.1,  # scan grid stepsize in nm
    dwell_time=1e-6,
)
```

where `scan_image` is a [HyperSpy](https://hyperspy.org/hyperspy-doc/current/user_guide/index.html)
`Signal2D` of size `scan_shape` scanned around `centre`.

![image](./scan.png)

> **NOTE:** the dwell time is simulated *realistically*, if your request to scan will take more than 15 seconds then the simulator will require you to override a safeguard so you don't have to wait minutes for an image...

### Coordinate system

The survey image is the definition of the coordinate system of the simulator - it will always have the same size in pixels `(512, 512)` and in nano-metres `(120, 120)`. All other requests to the simulator to run a scan are defined within this coordinate system.

For convenience the simulator provides helpers to transform between pixels in the survey image and nanometres, and vice-versa:

```python
py, px = 32, 46  # arbitrary pixel coordinate in the survey
(ny, nx) = simulator.survey.to_continuous((py, px))  # convert from (y, x) pixels to nm (y, x)
(py, px) = simulator.survey.to_pixels((ny, nx))  # convert from (y, x) nm to pixels (y, x)
(sy, sx) = simulator.survey.scaling  #  stepsize of the survey field of view in nm / pixel
(ey, ex) = simulator.survey.extent  # total size of the survey field of view in nm
```

All scan images have their origin defined in the survey coordinate system, so that (at least when drift is turned off) the centre of a particle in a scan image will have the same nano-metre coordinate in the low-resolution survey image.

### Drift corrector

The `simulator.scan()` method can accept a `drift_corrector` function, with the following form:

```python
def predict_drift(scan_time: float) -> tuple[float, float]:
    ...
    offset_nm = (y_offset, x_offset)
    return offset_nm
```

where `scan_time` is the start time of the new scan in seconds, as recorded in each image's metadata. The return value is a tuple `(y, x)` value in nano-metres which is added to the `centre` value inside `simulator.scan` before the scan grid is generated.

### Metadata

All returned images contains metadata about the scan for information:

```python
survey_image.metadata
```

returns the following:

- `current`: the beam current of the simulator in amps
- `dwell_time`: the dwell time of each scan point in seconds
- `rotation`: the rotation of the scan grid in degrees
- `scan_end`: the end time of the scan in seconds
- `scan_start`: the start time of the scan in seconds, as provided to the `drift_corrector`

If the image was acquired using a drift corrector function, then they image will contain additional metadata:

- `corrected_centre`: the centre of the scan after correction, in nano-metres

If the image is also a stack, then the stack also contains:

- `correction`: the correction applied to each image centre, as `y, x` offsets, in nano-metres

### Simulator GUI 
There is also a UI version of the simulator which will launch in a web browser, but this is only for demonstration purposes, not the coding exercise:

```python
simulator.show()
```

![image](./ui.png)

## HyperSpy basics

The simulator uses HyperSpy for all of its image outputs, in the form of [`Signal2D`](https://hyperspy.org/hyperspy-doc/current/user_guide/signal2d.html) objects, the API documentation for which [can be found here](https://hyperspy.org/hyperspy-doc/current/reference/api.signals/Signal2D.html#hyperspy.api.signals.Signal2D).

HyperSpy signals have an inbuilt axes calibration system, [documented here](https://hyperspy.org/hyperspy-doc/current/reference/base_classes/axes.html#hyperspy.axes.AxesManager), e.g.:

```python-repl
>>> survey_image.axes_manager
<Axes manager, axes: (|512, 512)>
            Name |   size |  index |  offset |   scale |  units
================ | ====== | ====== | ======= | ======= | ======
---------------- | ------ | ------ | ------- | ------- | ------
               x |    512 |      0 |       0 |    0.24 |     nm
               y |    512 |      0 |       0 |    0.24 |     nm
```

A `Signal2D` by default is just a single image as above (`axes: (|512, 512)`), but can also be a stack of images e.g. `axes: (8 |512, 512)` for an 8-image stack. The individual images of a stack can be accessed with `signal.inav[4]` to access the 5th image.

We can slice into the 2D image using continuous (nano-metre) coordinates (see [here](https://hyperspy.org/hyperspy-doc/current/user_guide/axes.html#the-navigation-and-signal-dimensions)):

```python
# slice an ROI with nanometres
survey_image.isig[12.3:24.9, 38.2:45.1]  # x0->x1, y0->y1 ranges in nanometres!
```

> **NOTE:** HyperSpy `isig` uses indexing as `(x, y)`, i.e. horizontal-vertical which is the opposite of `numpy` and matrix notation.

> **NOTE:** The slice values **must be floating point** i.e. `4.` not `4`, else they will be interpreted as pixel values and not nano-metres.

We can also plot our signals using HyperSpy, and use `matplotlib` to add additional annotations:

```python
%matplotlib widget
import matplotlib.pyplot as plt
survey_image.plot()
xcoord = [4.6, 8.2, 11.7]  # in nm
ycoord = [3.6, 6.3, 9.4]  # in nm
plt.plot(xcoord, ycoord, 'rx')  # x and y coords must be in nanometres as HyperSpy created the axes!
```

![image](./hyperspy-plot.png)

> **NOTE:** HyperSpy displays coordinates in the plot window as `(x, y)` in nanometres, but numpy arrays are indexed `[y, x]` in pixels!

Any HyperSpy signal has an underlying `numpy` array underneath which can be accessed using `signal.data`, if HyperSpy does not provide a processing method that you would like to use.

## Extension: Kalman Filter

A Kalman filter is a statistical technique to estimate both the tendency and noise in a time-series of measurements. It is often used in motion tracking and prediction tools, for example in GPS software. Try to implement a Kalman filter to smooth and better-predict the drift of the sample.

## GPU Implementation

Look into the `cupy` Python library and see if you can write the Python code to do drift estimation using the GPU.
