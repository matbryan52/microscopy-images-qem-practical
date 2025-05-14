import pathlib
import time
import operator
from threading import Lock
from typing import NamedTuple, TypeAlias, Self, Literal, Sequence, Callable

import numpy as np
from scipy import constants
import tqdm.auto as tqdm
import pandas as pd
from scipy.interpolate import RegularGridInterpolator
import pint
import hyperspy.api as hs
from hyperspy._signals.signal2d import Signal2D
from hyperspy.axes import UniformDataAxis, DataAxis

from .bezier_curve import generate_curve, QuadBezier


ureg = pint.UnitRegistry()
PositiveInt: TypeAlias = int
Degrees: TypeAlias = float
NanoMetres: TypeAlias = float
NMPerSecond: TypeAlias = float
Seconds: TypeAlias = float
PicoAmps: TypeAlias = float
ELECTRON_PER_PA = 1e-12 * (1 / constants.e)
DRIFT_HISTORY = 60 * 10

SCAN_WAIT = True
SCAN_DEAD_TIME = 0.2

class no_op_tqdm:
    def update(self, *args, **kwargs):
        pass

    def close(self, *args, **kwargs):
        pass


class YX(NamedTuple):
    y: float | np.ndarray
    x: float | np.ndarray

    def __binary_op(self, op, val):
        if isinstance(val, YX):
            return YX(
                y=op(self.y, val.y),
                x=op(self.x, val.x),
            )
        else:
            return YX(
                y=op(self.y, val),
                x=op(self.x, val),
            )

    def __mul__(self, val: float | int | Self):
        return self.__binary_op(operator.mul, val)

    def __truediv__(self, val: float | int | Self):
        return self.__binary_op(operator.truediv, val)

    def __floordiv__(self, val: float | int | Self):
        return self.__binary_op(operator.floordiv, val)

    def __mod__(self, val: float | int | Self):
        return self.__binary_op(operator.mod, val)

    def __add__(self, val: float | int | Self):
        return self.__binary_op(operator.add, val)

    def __sub__(self, val: float | int | Self):
        return self.__binary_op(operator.sub, val)

    def to_int(self):
        if self.is_scalar():
            return YX(int(self.y), int(self.x))
        else:
            return YX(self.y.astype(int), self.x.astype(int))

    def to_complex(self):
        return self.x + self.y * 1j

    def asarray(self, yx: bool = True):
        array = (
            np.atleast_2d(
                np.stack((
                    np.asarray(self.y),
                    np.asarray(self.x),
                ), axis=-1)
            )
        )
        if yx:
            return array
        return array[:, ::-1]

    def is_scalar(self):
        return np.isscalar(self.x) and np.isscalar(self.y)

    def rotate(self, angle: Degrees, about: 'YX'):
        if angle == 0.:
            return self
        angle = np.deg2rad(angle)
        about = YX(*about)
        assert about.is_scalar()
        translated = self - about
        transform = np.asarray([
            [np.cos(angle), -np.sin(angle)],
            [np.sin(angle), np.cos(angle)],
        ])
        points = translated.asarray(yx=False)
        rotated = points @ transform
        return YX(
            y=rotated[:, 1], x=rotated[:, 0]
        ) + about


PixelShapeYX: TypeAlias = YX
PixelYX: TypeAlias = YX
NanoMetreShapeYX: TypeAlias = YX
NanoMetreYX: TypeAlias = YX
NanoMetrePerPixelYX: TypeAlias = YX


class ScanDef(NamedTuple):
    tl: NanoMetreYX
    extent: NanoMetreShapeYX
    shape: PixelShapeYX

    @property
    def scaling(self) -> NanoMetrePerPixelYX:
        """
        Scale factors in Distance / Pixel
        """
        return self.extent / self.shape

    def to_continuous(self, point: PixelYX) -> NanoMetreYX:
        """
        Convert from survey pixel to continuous units
        """
        point = YX(*point)
        return point * self.scaling

    def to_pixels(self, point: NanoMetreYX) -> PixelYX:
        """
        Convert from continuous to survey pixel units
        """
        point = YX(*point)
        return point / self.scaling


class STEMImageSimulator:
    """
    A simulator for STEM imaging with stage drift and focus error

    Should normally be created with :py:meth:`~qem_practical.simulator.STEMImageSimulator.default`
    which automatically sets the `data` and `extent` parameters.

    Uses `HyperSpy <https://hyperspy.org/hyperspy-doc/current/index.html>`_ for image
    results, notably `Signal2D <https://hyperspy.org/hyperspy-doc/current/reference/api.signals/Signal2D.html#hyperspy.api.signals.Signal2D>`_.

    Parameters
    ----------
    data : np.ndarray
        The high-resolution 2D data to sample from, scaled from 0..1,
        nominally denoting a "scattering factor" for ADF imaging.
    extent : NanoMetreShapeYX
        The size of the data as a tuple `(y, x)`, nominally in nm
    current : PicoAmps, optional
        The beam current, by default 1, nominally in pico-amps
    drift_speed : NMPerSecond | Literal["random"], optional
        The drift rate of the sample, by default "random", in which case
        a sensible drift rate will be chosen, else a positive float in nm/s
    defocus : NanoMetres, optional
        A focus error on the sample plane, which is used to crudely
        simulate blurry imaging, by default 0.

    Example
    --------

    >>> from qem_practical.simulator import STEMImageSimulator
    >>> simulator = STEMImageSimulator.default()
    >>> survey_image = simulator.survey_image(1e-6)
    >>> scan = simulator.scan((12.3, 20.6), (64, 64), 1e-10)

    >>> simulator.show()  # launch the web-ui for this simulator
    """
    def __init__(
        self,
        data: np.ndarray,
        extent: NanoMetreShapeYX,
        current: PicoAmps = 1,
        drift_speed: NMPerSecond | Literal["random"] = "random",
        defocus: NanoMetres = 0.,
    ):
        self._scan_lock = Lock()
        self._shape = YX(*data.shape)
        self._extent = YX(*extent)
        cy = np.linspace(0, self._extent.y, num=data.shape[0], endpoint=True)
        cx = np.linspace(0, self._extent.x, num=data.shape[1], endpoint=True)
        self._interpolator = RegularGridInterpolator(
            (cy, cx),
            data,
            bounds_error=False,
            fill_value=None,
        )
        self._rng = np.random.default_rng()

        survey_fraction = 0.8
        self._survey_def = ScanDef(
            tl = self._extent * ((1 - survey_fraction) / 2),
            extent = self._extent * survey_fraction,
            shape=YX(512, 512),
        )
        self._current = current
        self._true_defocus = defocus
        self._defocus = 0.

        self._tstart = time.time()
        self._drift_gen = self._curve_generator(drift_speed)
        self._accumulated_drift = 0+0j
        self._drift_history = self._make_empty_drift_history()
        _ = next(self._drift_gen)

    @classmethod
    def default(
        cls,
        current: PicoAmps = 1,
        drift_speed: NMPerSecond | Literal["random"] = "random",
        defocus: NanoMetres = 0.,
    ) -> 'STEMImageSimulator':
        """
        Create a :class:`STEMImageSimulator` with the default nanoparticle data
        """
        rootdir = pathlib.Path(__file__).parent.parent.parent
        sim_data = np.load(rootdir / "data" / "particles.npz")
        return cls(
            **sim_data,
            current=current,
            drift_speed=drift_speed,
            defocus=defocus,
        )

    @staticmethod
    def _make_empty_drift_history():
        return {"p0": [], "p1": [], "p2": [], "time": []}

    def rel_time(self):
        return time.time() - self._tstart

    def reset_drift(self):
        if len(self._drift_history["p0"]) == 0:
            return
        with self._scan_lock:
            _, curve = self._drift_state
            self._accumulated_drift = curve.p2
            self._drift_history = self._make_empty_drift_history()

    def drift_history(self) -> pd.DataFrame:
        """
        Get a pandas DataFrame of drift history
        with index "time" in seconds, and "p0", "p1", "p2" in nm
        """
        return pd.DataFrame.from_dict(self._drift_history).set_index("time")

    def drift_for_times(self, times: Sequence[Seconds]):
        """
        Get the groundtruth drift value for timestamps in the recent past

        Parameters
        ----------

        times : Sequence[Seconds]
            Timestamps of images returned by this simulator, available as
            :code:`signal.metadata.scan_start.magnitude` or as :code:`signal.axes_metadata["time"].axis`
            for an image stack

        Returns
        -------

        pd.DataFrame
            A dataframe of absolute drift values with columns "timestamp", "yvals"
            and "xvals" in nanometres. Note the drifts are relative to `t==0` and so
            need to be normalised to the start of `times` if relative drift is desired.
        """
        df = self.drift_history()
        drifts = []
        for idx, timestamp in zip(np.floor(times), times):
            row = df.loc[int(idx)]
            bezier = QuadBezier(row["p0"], row["p1"], row["p2"])
            drifts.append(bezier.coordinate_at(timestamp % 1))
        drifts = np.asarray(drifts)
        return pd.DataFrame.from_dict(dict(
            timestamp=times,
            yvals=drifts.imag,
            xvals=drifts.real,
        ))

    def _curve_generator(self, speed: float | Literal["random"] = 1.):
        if isinstance(speed, str) and speed == "random":
            speed = float(np.random.uniform(low=0.5, high=0.8))
        for curve_idx, curve in enumerate(
            generate_curve(scale=speed),
            # start=-1,
        ):
            self._drift_state = curve_idx, curve
            if len(self._drift_history["time"]) > DRIFT_HISTORY:
                _ = [v.pop(0) for v in self._drift_history.values()]
            self._drift_history["p0"].append(-1 * (curve.p0 - self._accumulated_drift))
            self._drift_history["p1"].append(-1 * (curve.p1 - self._accumulated_drift))
            self._drift_history["p2"].append(-1 * (curve.p2 - self._accumulated_drift))
            self._drift_history["time"].append(int(curve_idx))
            yield self._drift_state
    
    def _drift_for_times(self, start: Seconds, number: int, step: Seconds):
        coordinates = []
        curve_idx, curve = self._drift_state
        int_tval = np.floor(start)
        num_in_curve = int(1. / step)
        tvals = np.linspace(0., 1., num=num_in_curve)
        start_in_curve = int((start % 1) * num_in_curve)
        while number > 0:
            if int_tval < curve_idx:
                raise RuntimeError("Cannot index into past")
            while int_tval > curve_idx:
                curve_idx, curve = next(self._drift_gen)
            assert int_tval == curve_idx
            rel_times = tvals[start_in_curve: min(num_in_curve, start_in_curve + number)]
            coordinates.append(
                curve.coordinate_at(rel_times)
            )
            int_tval += 1
            number -= rel_times.size
            start_in_curve = 0
        return np.concatenate(coordinates, axis=0)

    @property
    def _defocus_value(self) -> float:
        return abs(self._true_defocus - self._defocus)

    @property
    def _defocus_points(self) -> int:
        return 9

    def set_focus(self, val: NanoMetres):
        self._defocus = val

    def _apply_defocus(self, point: YX):
        df = self._defocus_value
        dp = self._defocus_points
        angles = np.linspace(0., 2 * np.pi, num=dp, endpoint=True)
        offsets = df * np.exp(1j * angles)
        offsets[0] = 0 + 0j
        yvals = np.tile(point.y[:, np.newaxis], (1, dp))
        xvals = np.tile(point.x[:, np.newaxis], (1, dp))
        yvals += offsets.imag
        xvals += offsets.real
        return YX(yvals.ravel(), xvals.ravel())

    def _apply_drift(
        self,
        grid: YX,
        scan_start: Seconds,
        dwell_time: Seconds,
    ):
        drift = self._drift_for_times(scan_start, grid.x.size, dwell_time)
        drift = YX(drift.imag, drift.real)
        return grid + drift

    def _wrap_coordinate(self, yx: YX):
        return yx % self._extent

    @staticmethod
    def _get_grid(tl: YX, extent: YX, shape: YX, rotation: Degrees):
        y0 = tl.y
        x0 = tl.x
        br = tl + extent
        y1 = br.y
        x1 = br.x
        h, w = shape
        y_coords = np.linspace(y0, y1, num=h, endpoint=True)
        x_coords = np.linspace(x0, x1, num=w, endpoint=True)
        xx, yy = np.meshgrid(x_coords, y_coords)
        grid = YX(yy.ravel(), xx.ravel())
        grid = grid.rotate(rotation, tl + extent / 2)
        return grid

    def _sample(self, grid_coords: YX, dwell_time: float):
        scattering_factor = self._interpolator(grid_coords)
        samples = self._rng.poisson(
            lam=scattering_factor * (self._current * dwell_time * ELECTRON_PER_PA)
        )
        return samples

    def _scan(
        self,
        *,
        tl: NanoMetreYX,  # top-left in the *survey* coordinate system
        extent: NanoMetreShapeYX,
        shape: PixelShapeYX,
        dwell_time: Seconds,
        drift_corrector: Callable[[Seconds], NanoMetreYX] | None = None,
        rotation: Degrees = 0.,
        wait: bool | str = False,
        progress: bool = True,
    ) -> Signal2D:
        with self._scan_lock:
            tstart = time.perf_counter()
            # could add a scan pattern option
            shape = YX(*shape)
            scan_start = self.rel_time()
            correction = None
            if drift_corrector is not None:
                correction = YX(*drift_corrector(scan_start))
                tl = tl + correction
            effective_tl = tl + self.survey.tl
            scan_end = scan_start + np.prod(shape) * dwell_time
            grid = self._get_grid(effective_tl, extent, shape, rotation)
            grid = self._apply_drift(grid, scan_start, dwell_time)
            has_defocus = self._defocus_value > 0.
            if has_defocus:
                grid = self._apply_defocus(grid)
            grid = self._wrap_coordinate(grid)
            image = (
                self._sample(
                    (grid.y, grid.x),
                    dwell_time,
                )
            )
            if has_defocus:
                dp = self._defocus_points
                image = image.reshape(-1, dp).mean(axis=-1)
                grid = YX(grid.y[::dp], grid.x[::dp])
            image = image.reshape(shape)
            tspent = time.perf_counter() - tstart
            npts = grid.x.size
            true_time = npts * dwell_time
            time_to_wait = max(0, (true_time - tspent))
            if wait:
                effective_dwell_time = time_to_wait / npts
                step = 256
                if progress:
                    bar = tqdm.tqdm(total=npts, desc=wait if isinstance(wait, str) else "Scanning")
                else:
                    bar = no_op_tqdm()
                for idx in range(0, npts, step):
                    bar.update(min(step, npts - idx))
                    if effective_dwell_time > 0:
                        time.sleep(effective_dwell_time * step)
                if progress:
                    bar.close()
            else:
                self._tstart -= time_to_wait
        scales = extent / shape
        image = Signal2D(
            image,
            axes=[
                UniformDataAxis(
                    index_in_array=0,
                    name="y",
                    units="nm",
                    offset=tl.y,
                    size=shape.y,
                    scale=scales.y,
                ),
                UniformDataAxis(
                    index_in_array=1,
                    name="x",
                    units="nm",
                    offset=tl.x,
                    size=shape.x,
                    scale=scales.x,
                ),
            ],
            metadata=dict(
                scan_start=scan_start * ureg.second,
                scan_end=scan_end * ureg.second,
                dwell_time=dwell_time * ureg.second,
                rotation=rotation * ureg.degree,
                current=self._current * 1e-12 * ureg.ampere,
                correction=correction,
            ),
        )
        return image

    @property
    def survey(self) -> ScanDef:
        """
        Get the definition of the survey image coordinate system
        with methods to convert from survey pixels to continuous units
        """
        return self._survey_def

    def survey_image(self, dwell_time: Seconds, progress: bool = True) -> Signal2D:
        """
        Acquire a new survey image with the given dwell time
        """
        image = self._scan(
            tl=YX(0., 0.),
            extent=self.survey.extent,
            shape=self.survey.shape,
            dwell_time=dwell_time,
            wait="Survey" if SCAN_WAIT else False,
            progress=progress,
        )
        image.metadata.General.title = "Survey image"
        return image

    def scan(
        self,
        centre: NanoMetreYX,
        scan_shape: PixelShapeYX,
        scan_step: NanoMetres,
        dwell_time: Seconds,
        *,
        stack: PositiveInt | None = None,
        drift_corrector: Callable[[Seconds], NanoMetreYX] | None = None,
        rotation: Degrees = 0.,
        with_grid: bool = False,
        progress: bool = True,
    ) -> Signal2D | tuple[Signal2D, YX]:
        """
        Acquire a scan image centered at a specified point.

        Performs a raster scan over a rectangular region centered 
        at the given survey coordinates, with optional rotation. 
        The scan is defined by its shape (in points), step size (in nanometres), 
        and dwell time per pixel (in seconds).

        Parameters
        ----------

        centre : NanoMetreYX
            The center of the scan grid in continuous survey coordinates.
        scan_shape : PixelShapeYX
            The dimensions (rows, columns) of the scan as integer points.
        scan_step : NanoMetres
            The distance between scan points in nanometres.
        dwell_time : Seconds
            The dwell time of each scan point
        stack : PositiveInt, optional
            The number of scans to perform sequentially using the same
            scan coordinates (default is None)
        drift_corrector : Callable[[Seconds], NanoMetreYX], optional
            A function which takes the timestamp of the start of the scan
            being run and returns a displacement of :code:`centre`, :code:`(dy, dx)`,
            in nanometres to nominally correct drift. This function will be
            called just before the start of each scan when acquiring a `stack`.
        rotation : Degrees, optional
            Angle to rotate the scan grid (default is 0 degrees). Positive is anticlockwise.
        with_grid : bool, optional
            If True, also return the grid coordinates used in the scan (default is False).
        progress: bool, optional
            If True, display a progress bar during the scan (default is True).

        Returns
        -------

        image : Signal2D
            The acquired scan image as a HyperSpy `Signal2D` with calibration and metadata.
            If `stack` is not None then the returned image will have an additional navigation
            dimension calibrated to the start time of each scan acquisition.
        grid : YX, optional
            The scan grid in survey continuous coordinates, only returned if `with_grid` is True.

        Notes
        -----

        The returned grid, if requested, is relative to the survey's top-left origin.
        """
        centre = YX(*centre)
        scan_shape = YX(*scan_shape)
        is_stack = stack is not None
        if is_stack:
            assert stack >= 1, "Stack must be a positive integer"
        if stack is None:
            stack = 1
        extent = scan_shape * scan_step
        tl = centre - (extent / 2)
        signals = []
        iterator = (
            tqdm.trange(stack, desc="Stack acquisition")
            if (is_stack and progress)
            else range(stack)
        )
        for _ in iterator:
            image = self._scan(
                tl=tl,
                extent=extent,
                shape=scan_shape,
                dwell_time=dwell_time,
                drift_corrector=drift_corrector,
                rotation=rotation,
                wait="Scanning" if SCAN_WAIT else False,
                progress=progress and not is_stack,
            )
            image.metadata.General.title = "Scan"
            signals.append(image)
            if is_stack:
                time.sleep(SCAN_DEAD_TIME)
        if not is_stack:
            image = signals[0]
        else:
            stack_data = np.stack(tuple(s.data for s in signals), axis=0)
            image = Signal2D(
                stack_data,
                metadata=dict(signals[0].metadata),
            )
            image.axes_manager.set_axis(
                DataAxis(
                    name="time",
                    units="second",
                    axis=[s.metadata.scan_start.magnitude for s in signals],
                    navigate=True,
                ),
                0,
            )
            image.axes_manager.set_axis(
                signals[0].axes_manager["y"],
                1,
            )
            image.axes_manager.set_axis(
                signals[0].axes_manager["x"],
                2,
            )
            image.metadata.scan_end = signals[-1].metadata.scan_end
        if drift_corrector is not None:
            true_tl = YX(
                np.asarray([s.axes_manager["y"].offset for s in signals]),
                np.asarray([s.axes_manager["x"].offset for s in signals]),
            )
            image.metadata.corrected_centre = true_tl + (extent / 2)
            if is_stack:
                image.metadata.correction = YX(
                    y=np.asarray([s.metadata.correction.y for s in signals]),
                    x=np.asarray([s.metadata.correction.x for s in signals]),
                )
        if with_grid:
            grid = self._get_grid(tl, extent, scan_shape, rotation)
            return image, grid - self.survey.tl  # in continuous coords
        return image

    def show(self):
        """
        Launch the GUI webapp for this simulator
        """
        from .simulator_ui import simulator_ui
        simulator_ui(self).show(
            title="STEM Image Simulator",
            open=True,
        )
