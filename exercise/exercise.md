# QEM 2025 Practical Session

This document describes the practical session for QEM2025 related to image processing.

## Setup

From a terminal activate the `conda` environment using:

```bash
conda activate TP_AI
```

Then update the course materials using

```bash
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

The simulator object has two user-facing methods:

```python
survey_image = simulator.survey_image(dwell_time=1e-6)  # seconds
```

where `survey_image` is always a `512x512` [HyperSpy](https://hyperspy.org/hyperspy-doc/current/user_guide/index.html)
`Signal2D` image of the field of view.

Secondly:

```python
scan_image = simulator.scan(
    centre=(219, 307),  # centre of the scan grid in pixel coordinates of the survey image
    scan_shape=(64, 64),  # scan grid shape-YX
    scan_step=0.1,  # scan grid stepsize in nm
    dwell_time=1e-6,
)
```

where `scan_image` is a [HyperSpy](https://hyperspy.org/hyperspy-doc/current/user_guide/index.html)
`Signal2D` of size `scan_shape` scanned around `centre`.

The `Signal2D` images are calibrated to the coordinate system of the simulator:

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

We can also plot signals using HyperSpy:

```python
import matplotlib.pyplot as plt
survey_image.plot()
plt.show()
```
<!-- A helper for the survey image coordinate system is also available at 

```python
survey_def = simulator.survey
```

with properties:

```python
(sy, sx) = survey_def.scaling  #  scaling of the survey field of view in nm / pixel
(ey, ex) = survey_def.extent  # shape of the survey field of view in nm
```

and methods

```python
(ny, nx) = survey_def.to_continuous((py, px))  # convert from pixels to nanometres
(py, px) = survey_def.to_pixels((ny, nx))  # convert from nanometres to pixels
``` -->

There is also a UI version of the simulator which will launch in a web browser with:

```python
simulator.show()
```

## Exercises

In order of increasing difficulty, with no obligation to complete all steps.

### 1 - Detect, image and measure particles without drift

Create the simulator with argument `drift_speed=0.` to disable drifting. This means we can treat the survey image as *static* and measure any particle within the field of view without distortion or tracking.

- From a survey image taken at a long dwell time locate all of the particles in the field of view using a peak-finding or similar approach
- For some of the detected particles run a detailed STEM scan of each and display the high-resolution images on the same figure
- For each high-resolution image segment the particle from the background and measure its properties (e.g. diameter, circumference, area, circularity). Try to express the measurements in *nanometres* rather than pixels based on the information you have about each scan.
- Plot the distributions of the above values as histograms.

### 2 - Estimate the drift rate and direction

Create a simulator with a random drift speed `drift_speed="random"`. The survey image will now change over time as particles move through the field of view. The drift rate will be approximately constant while the drift direction slowly changes over time.

- Create a survey image with a short dwell time
- Identify a cluster of particles to scan in detail
- Scan the particles repeatedly and estimate the drift vector between successive frames
- Plot the sum of the drift vector over time and compare it to the simulator's true drift curve that can be accessed with:

```python
# drift_dataframe contains columns "time", "xvals", "yvals"
drift_dataframe = simulator.drift_history()
```

### 3 - Post-acquisition alignment of an image stack

Create another simulator with sample drift.

- Acquire a sequence of STEM scans of the same area with a moderate dwell time
  - This can be acheived with `simulator.scan(..., stack=8)` to acquire an 8-image stack.
- Estimate the drift between each pair of images, as in exercise 2.
- Super-impose the images using interpolation to account for the drift
- Display the summed image stack

### 4 - Live drift correction

If we can estimate the drift rate periodically between acquisitions then we can track a feature over a longer period of time by shifting the scan grid to compensate. In a real microscope you might do this by adjusting *beam shift* though in the simulator the API can scan arbitrary grids.

- Acquire a survey image and select a particle to track
- Alternate between drift estimation and imaging steps
  - The drift can be computed on the particle being tracked or from a larger field of view scan.
- Shift the scan grid with the drift vector to track a particle to the edge of the frame
  - Consider taking into account the time between the measurement of the drift and the next scan.
- Generate a GIF of the scan images using `imageio`
