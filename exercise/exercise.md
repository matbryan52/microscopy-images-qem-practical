# QEM 2025 Image Processing Practical Session

Describes the practical session for QEM2025 related to image processing.

## Setup

The working directory `TP Images` is on the Desktop. Inside there is a shortcut to open a `Terminal` with the correct `conda` environment activated. If you don't see `(TP_AI)` before the prompt then activate the `conda` environment using:

```powershell
conda activate TP_AI
```

If `conda` is not recognized as a command then run:

```powershell
C:\ProgramData\anaconda3\shell\condabin\conda-hook.ps1
```

then run the `activate` command from above.

You can then update the course materials using:

```powershell
tp-update
```

## Objective

The objective is to carry out STEM imaging measurements of a sample of gold nanoparticles using on a simulated microscope suffering from severe sample drift. Imaging quickly to mitigate the drift leads to poor signal-to-noise ratio images, while slowy scanning too large an area adds distortion as the sample drifts during a scan.

There are multiple approaches to measure the particles and acquire enough data to display a particle size distribution.

## Simulator

The simulator reproduces ADF-STEM imaging on a sample of nanoparticles which are drifting through the field of view. The simulator can be created like so:

```python
import numpy as np
from qem_practical.simulator import STEMImageSimulator

sim_data = np.load("data/particles.npz")
simulator = STEMImageSimulator(**sim_data)
```

The simulator object has two primary user-facing methods, one to acquire a survey image:

```python
survey_image = simulator.survey_image(dwell_time=1e-6)  # seconds
```

where `survey_image` is a `512x512` [HyperSpy](https://hyperspy.org/hyperspy-doc/current/user_guide/index.html)
`Signal2D` image of the field of view.

![image](./survey-image.png)

Ando one to acquire a STEM scan:

```python
scan_image = simulator.scan(
    centre=(61.3, 34.2),  # centre of the scan grid in the coordinate system of the survey image
    scan_shape=(100, 180),  # scan grid shape-YX (integer)
    scan_step=0.1,  # scan grid stepsize in nm
    dwell_time=1e-6,
)
```

where `scan_image` is a [HyperSpy](https://hyperspy.org/hyperspy-doc/current/user_guide/index.html)
`Signal2D` of size `scan_shape` scanned around `centre`.

![image](./scan.png)

The output `Signal2D` images are calibrated to the coordinate system of the simulator:

```python-repl
>>> survey.axes_manager
<Axes manager, axes: (|512, 512)>
            Name |   size |  index |  offset |   scale |  units
================ | ====== | ====== | ======= | ======= | ======
---------------- | ------ | ------ | ------- | ------- | ------
               x |    512 |      0 |       0 |    0.24 |     nm
               y |    512 |      0 |       0 |    0.24 |     nm
```

and so can be used for coordinate transformations:

```python-repl
# nm to pixels
x_px = survey.axes_manager["x"].value2index(62.3)
```

and slice into an image using continuous coordinates:

```python
# slice an ROI with nanometres
survey.isig[12.3: 24.9, 38.2: 45.1]
```

For convenience the simulator also provides its own coordinate transformation helpers:

```python
(ny, nx) = simulator.survey.to_continuous((py, px))  # convert from pixels to nanometres
(py, px) = simulator.survey.to_pixels((ny, nx))  # convert from nanometres to pixels
(sy, sx) = simulator.survey.scaling  #  scaling of the survey field of view in nm / pixel
(ey, ex) = simulator.survey.extent  # size of the survey field of view in nm
```

We can also plot signals using HyperSpy:

```python
import matplotlib.pyplot as plt
survey_image.plot()
plt.show()
```

![image](./hyperspy-plot.png)

The returned `Signal2D` also contains metadata about the scan:

```python-repl
>>> survey.metadata
title = Survey image
current = <Quantity(1e-11, 'ampere')>
dwell_time = <Quantity(1e-05, 'second')>
rotation = <Quantity(0.0, 'degree')>
scan_end = <Quantity(2.62452228, 'second')>
scan_start = <Quantity(0.00308227539, 'second')>
```

There is also a UI version of the simulator which will launch in a web browser with:

```python
simulator.show()
```

![image](./ui.png)

## Exercises

In order of increasing difficulty, with no obligation to complete all steps.

### 1 - Detect, image and measure particles without drift

Create the simulator with argument `drift_speed=0.` to disable drifting. This means we can treat the survey image as *static* and measure any particle within the field of view without distortion or tracking.

- From a survey image taken at a long dwell time locate all of the particles in the field of view using a peak-finding or similar approach
- For some of the detected particles run a detailed STEM scan of each and display the high-resolution images on the same figure
- For each high-resolution image segment the particle from the background and measure its properties (e.g. diameter, circumference, area, circularity). Try to express the measurements in *nanometres* rather than pixels based on the information you have about each scan.
- Plot the distributions of the above values as histograms.

### 2 - Estimate the drift and correct an image stack

Create a simulator with a random drift speed `drift_speed="random"`. The survey image will now change over time as particles move through the field of view. The drift rate will be approximately constant while the drift direction slowly changes over time.

- Create a survey image with a short dwell time
- Identify or choose a cluster of particles to scan in detail
- Scan the particles repeatedly and estimate the drift vector between successive frames
  - This can be acheived with `simulator.scan(..., stack=8)` to acquire an 8-image stack.
- Plot the drift over time and compare it to the simulator's true drift curve that can computed with:

```python
# drift_dataframe contains columns "timestamp", "yvals", "xvals" in nanometres
timestamps = stack.axes_manager["time"].axis
drift_dataframe = simulator.drift_for_time(timestamps)
```

- Super-impose the acquired images using interpolation to correct for the drift
- Display the summed image stack

### 3 - Live drift correction

If we can estimate the drift rate periodically between acquisitions then we can track a feature over a longer period of time by shifting the scan grid to compensate. In a real microscope you might do this by adjusting *beam shift* though in the simulator the API can scan arbitrary grids.

- Acquire a survey image and select a particle to track
- Alternate between drift estimation and imaging steps
  - The drift can be computed on the particle being tracked or from a larger field of view scan.
- Shift the scan grid with the drift vector to track a particle to the edge of the frame
  - Consider taking into account the time between the measurement of the drift and the next scan.
- Generate a GIF of the scan images using `imageio`


## Notes and hints

HyperSpy can handle more than just spectra; it has a number of image processing features which will **very** be useful for the exercises. Consider reading the user guide of [Signal2D](https://hyperspy.org/hyperspy-doc/current/user_guide/signal2d.html) and its [documentation](https://hyperspy.org/hyperspy-doc/current/reference/api.signals/Signal2D.html#hyperspy.api.signals.Signal2D).
