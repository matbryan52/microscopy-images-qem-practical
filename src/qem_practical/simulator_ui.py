import numpy as np
import panel as pn
from itertools import pairwise
import humanize
from bokeh.core.properties import value as bkvalue
from bokeh.models import LinearAxis, Range1d, Legend, LegendItem, Text
from bokeh.plotting import figure
from skimage.registration import phase_cross_correlation
pn.extension("floatpanel")

from libertem_ui.figure import ApertureFigure, set_frame_height
from libertem_ui.display.display_base import Rectangles, Curve, PointSet
from .simulator import STEMImageSimulator, YX

MAXDIM = 512


def interp_sequence(times, period):
    if len(times) == 0:
        raise
    elif len(times) == 1:
        yield times[0]
        return
    for t0, t1 in pairwise(times):
        interval = t1 - t0
        if period > interval:
            yield t0
        else:
            yield from np.linspace(t0, t1, num=int(interval / period), endpoint=False)


class DriftEstimator:
    def __init__(self):
        self.reset()

    def reset(self):
        self._current_drift = np.asarray((0., 0.))  # in pixels
        self._last_roi = None
        self._last_roi_slice = None
        self._drift_history = {"xvals": [0.], "yvals": [0.], "timestamp": [0.]}

    def current_drift_nm(self):
        dy, dx = self._drift_history["yvals"][-1], self._drift_history["xvals"][-1]
        return YX(dy, dx)

    def current_drift_rate(self, pts: int = 10):
        yvals = np.asarray(self._drift_history["yvals"][-pts:])
        if yvals.size <= 1:
            return None
        xvals = np.asarray(self._drift_history["xvals"][-pts:])
        timestamps = np.asarray(self._drift_history["timestamp"][-pts:])

        cvals = xvals + 1j * yvals
        b = np.cumsum(np.abs(np.diff(cvals))).reshape(-1, 1)
        timestamps = timestamps[1:]
        A = np.stack((timestamps, np.ones(timestamps.size)), axis=1)
        m, _ = np.linalg.lstsq(
            A, b,
        )[0]
        return m.item()  # nm / s        

    def estimate(self, survey, rectangles):
        roi_data = rectangles.cds.data
        scale = survey.axes_manager["x"].scale
        if len(roi_data["cx"]) > 0:
            cx, cy = int(roi_data["cx"][0]), int(roi_data["cy"][0])
            w, h = int(abs(roi_data["w"][0])), int(abs(roi_data["h"][0]))
            w2, h2 = w // 2, h // 2
            roi_slice = np.s_[cy - h2: cy + h2 + 1, cx - w2: cx + w2 + 1]
            drift_roi = survey.data[roi_slice]
            drift_roi = np.fft.fft2(drift_roi)
            if self._last_roi_slice is not None and self._last_roi_slice != roi_slice:
                self.reset()
            if self._last_roi is not None:
                this_drift, _, _ = phase_cross_correlation(
                    self._last_roi,
                    drift_roi,
                    space="fourier",
                    upsample_factor=10,
                )
                self._current_drift -= this_drift  # in px
                # convert to nm for display
                new_y = self._drift_history["yvals"][-1] - this_drift[0] * scale
                new_x = self._drift_history["xvals"][-1] - this_drift[1] * scale
                self._drift_history["yvals"].append(new_y)
                self._drift_history["xvals"].append(new_x)
                self._drift_history["timestamp"].append(survey.metadata.scan_start.magnitude)
            else:
                self._drift_history["timestamp"][0] = survey.metadata.scan_start.magnitude
            self._last_roi = drift_roi
            self._last_roi_slice = roi_slice
        return self._current_drift  # in pixels


def add_cal_axes(fig, extent, label):
    yrange, xrange = extent.y, extent.x
    fig.extra_y_ranges['cal'] = Range1d(yrange, 0.)
    fig.extra_x_ranges['cal'] = Range1d(0., xrange)

    axy = LinearAxis(
        axis_label=label,
        y_range_name="cal",
    )
    fig.add_layout(axy, 'left')

    axx = LinearAxis(
        axis_label=label,
        x_range_name="cal",
    )
    fig.add_layout(axx, 'below')


def update_cal_axes(fig, extent):
    yrange, xrange = extent.y, extent.x
    fig.extra_y_ranges['cal'].start = yrange
    fig.extra_x_ranges['cal'].end = xrange


def simulator_ui(simulator: STEMImageSimulator):
    survey_dwell_time = 0.000_001
    survey = simulator.survey_image(survey_dwell_time, progress=False).data
    survey_fig = (
        ApertureFigure
        .new(
            survey.astype(np.float32),
            title="Survey image",
            maxdim=MAXDIM,
            downsampling=False,
        )
    )

    h, w = survey.shape
    survey_fig.fig.x_range.bounds = (0, w)
    survey_fig.fig.y_range.bounds = (0, h)
    add_cal_axes(survey_fig.fig, simulator.survey.extent, "Survey (nm)")

    rectangles = (
        Rectangles
        .new()
        .empty()
        .on(survey_fig.fig)
        .editable(selected=True)
    )

    rectangles.rectangles.fill_color = "Crimson"
    rectangles.rectangles.line_color = "Crimson"

    scan_text = Text(x="cx", y="cy", text=bkvalue("Scan ROI"), text_color="Crimson", text_align="center", text_baseline="middle")
    survey_fig.fig.add_glyph(rectangles.cds, scan_text)

    tools = rectangles.tools("rectangles", survey_fig.fig)
    tools[survey_fig.fig][0].num_objects = 1

    corrected_rectangles = (
        Rectangles
        .new()
        .empty()
        .on(survey_fig.fig)
    )
    corrected_rectangles.rectangles.fill_color = "DarkOrange"
    corrected_rectangles.rectangles.fill_alpha = 0.1
    corrected_rectangles.rectangles.line_color = "DarkOrange"

    corrected_text = Text(x="cx", y="cy", text=bkvalue("Corrected"), text_color="DarkOrange", text_align="center", text_baseline="middle")
    survey_fig.fig.add_glyph(corrected_rectangles.cds, corrected_text)

    drift_roi = (
        Rectangles
        .new()
        .empty()
        .on(survey_fig.fig)
        .editable(
            selected=False,
            tag_name="drift_roi",
        )
    )
    drift_roi.rectangles.fill_color = "CornflowerBlue"
    drift_roi.rectangles.line_color = "CornflowerBlue"

    drift_text = Text(x="cx", y="cy", text=bkvalue("Drift ROI"), text_color="CornflowerBlue", text_align="center", text_baseline="middle")
    survey_fig.fig.add_glyph(drift_roi.cds, drift_text)

    tools = drift_roi.tools("rectangles", survey_fig.fig)
    tools[survey_fig.fig][0].num_objects = 1

    estimate_drift_button = pn.widgets.Toggle(
        name="Enable drift estimation",
        value=False,
        width_policy="max",
        button_type="default",
    )
    estimate_correction_button = pn.widgets.Toggle(
        name="Enable correction",
        value=True,
        width_policy="max",
        button_type="default",
    )
    drift_estimator = DriftEstimator()

    drift_fig = figure(title='Drift', match_aspect=True)
    drift_fig_pane = pn.pane.Bokeh(drift_fig)
    drift_curve = (
        Curve
        .new()
        .empty()
        .on(drift_fig)
    )
    drift_curve_points = (
        PointSet(
            drift_curve.cds,
            x="xvals",
            y="yvals",
        )
        .on(drift_fig)
    )
    drift_curve_points.points.fill_color = None
    drift_curve_points.points.line_color = "black"
    drift_fig.xaxis.axis_label="x-drift (nm)"
    drift_fig.yaxis.axis_label="y-drift (nm)"
    drift_fig.y_range.flipped = True
    true_drift_curve = (
        Curve
        .new()
        .empty()
        .on(drift_fig)
    )
    true_drift_curve.glyph.line_dash = "dashed"

    true_drift_renderer = true_drift_curve.renderers_for_fig("curve", drift_fig)[0]
    drift_renderer = drift_curve.renderers_for_fig("curve", drift_fig)[0]
    legend = Legend(
        items=[
            LegendItem(label="Estimated Drift", renderers=[drift_renderer]),
            LegendItem(label="True Drift", renderers=[true_drift_renderer])
        ],
        location="top_right",
        orientation="vertical",
    )
    drift_fig.add_layout(legend, "center")

    live_survey_button = pn.widgets.Toggle(
        name="Live survey",
        value=False,
        width_policy="max",
        button_type="warning",
    )
    single_survey = pn.widgets.Button(
        name="Single survey",
        disabled=False,
        button_type="success",
        width_policy="max",
    )
    live_survey_button.jslink(single_survey, **{"value": "disabled"})

    survey_spinner = pn.indicators.LoadingSpinner(
        value=False,
        width=35,
        height=35,
        bgcolor="dark",
        color="success",
    )

    drift_info_md = pn.pane.Markdown(object="No drift information")

    def _format_drift_info():
        drift_yx = drift_estimator.current_drift_nm()
        drift_rate = drift_estimator.current_drift_rate()
        if drift_rate is None:
            drift_rate = 0.
        return f"""- **Current drift**: (x, y) = {drift_yx.x:.1f}, {drift_yx.y:.1f} *nm*
- **Drift rate**: {drift_rate:.1f} *nm / s*
"""

    def update_survey(*e):
        try:
            survey_spinner.value = True
            survey = simulator.survey_image(survey_dwell_time, progress=False)
            survey_fig.update(
                survey.data.astype(np.float32)
            )
            if estimate_drift_button.value:
                current_drift = drift_estimator.estimate(survey, drift_roi)
                drift_curve.update(
                    xvals=drift_estimator._drift_history["xvals"],
                    yvals=drift_estimator._drift_history["yvals"],
                )
                timestamps = drift_estimator._drift_history["timestamp"]
                drifts = simulator.drift_for_times(tuple(interp_sequence(timestamps, 0.1)))
                true_drift_curve.update(
                    xvals=drifts["xvals"] - drifts["xvals"][0],
                    yvals=drifts["yvals"] - drifts["yvals"][0],
                )
                scan_roi = rectangles.cds.data
                if len(scan_roi["cx"]) > 0:
                    corrected_rectangles.cds.data.update(
                        cx=[scan_roi["cx"][0] + current_drift[1]],
                        cy=[scan_roi["cy"][0] + current_drift[0]],
                        w=scan_roi["w"],
                        h=scan_roi["h"],
                    )
                drift_info_md.object = _format_drift_info()
        finally:
            survey_spinner.value = False

    update_cb = pn.state.add_periodic_callback(
        update_survey,
        period=1000,
        start=False,
    )

    def toggle_update(e):
        if e.new and not update_cb.running:
            update_cb.start()
            live_survey_button.name = "Stop..."
        elif not e.new and update_cb.running:
            update_cb.stop()
            live_survey_button.name = "Live survey"
        else:
            update_cb.stop()
            live_survey_button.value = False
            live_survey_button.name = "Live survey"

    live_survey_button.param.watch(toggle_update, "value")
    single_survey.on_click(update_survey)

    scan_step_input = pn.widgets.Select(
        name="Scan step (nm)",
        value="0.2",
        options=[
            "0.05", "0.1", "0.2", "0.3", "0.5", "0.7", "1.0"
        ],
        width_policy="max",
    )

    dwell_time_input = pn.widgets.Select(
        name="Dwell time (µs)",
        value="10",
        options=[
            "0.1", "1", "10", "100", "1000",
        ],
        width_policy="max",
    )

    sum_stack_input = pn.widgets.Select(
        name="Stack-depth (summed)",
        value="1",
        options=[
            "1", "2", "4", "8",
        ],
        width_policy="max",
    )

    scan_shape = (64, 64)
    scan = np.zeros(scan_shape, dtype=np.float32)
    scan_fig = (
        ApertureFigure
        .new(
            scan,
            title="Scan",
            downsampling=False,
        )
    )

    add_cal_axes(scan_fig.fig, simulator.survey.extent, "Scan (nm)")

    scan_button = pn.widgets.Button(
        name="Scan",
        button_type="success",
        width_policy="max",
    )
    # live_survey_button.jslink(scan_button, **{"value": "disabled"})
    scan_spinner = pn.indicators.LoadingSpinner(
        value=False,
        width=35,
        height=35,
        bgcolor="dark",
        color="success",
    )


    def do_scan(*e):
        data = rectangles.cds.data
        if len(data["cx"]) == 0:
            return
        if estimate_drift_button.value and estimate_correction_button.value and len(corrected_rectangles.cds.data["cx"]) > 0:
            data = corrected_rectangles.cds.data
        try:
            scan_button.disabled = True
            scan_spinner.value = True
            # live_survey_button.disabled = True
            # single_survey.disabled = True
            cx, cy = data["cx"][0], data["cy"][0]
            w, h = abs(data["w"][0]), abs(data["h"][0])

            extent = YX(h, w) * simulator.survey.scaling
            scan_step = float(scan_step_input.value)
            scan_shape = (extent / scan_step).to_int()
            dwell_time = float(dwell_time_input.value) * 1e-6

            stack = int(sum_stack_input.value)
            stack = None if stack == 1 else stack
            scan_img = simulator.scan(
                simulator.survey.to_continuous(YX(cy, cx)), scan_shape, scan_step, dwell_time,
                rotation=0, progress=False, stack=stack,
            ).data
            if stack is not None:
                scan_img = scan_img.sum(axis=0)
            update_cal_axes(scan_fig.fig, extent)
            set_frame_height(scan_fig.fig, scan_img.shape, maxdim=MAXDIM)
            scan_fig.update(scan_img.astype(np.float32))
        finally:
            scan_button.disabled = False
            scan_spinner.value = False
            # live_survey_button.disabled = False
            # single_survey.disabled = False

    scan_button.on_click(do_scan)

    survey_fig._outer_toolbar.height = 0
    scan_fig._outer_toolbar.height = 0

    def scan_info_str():
        stub = ""
        data = rectangles.cds.data
        if len(data["cx"]) == 0:
            return stub + """

No ROI defined
"""
        w, h = abs(data["w"][0]), abs(data["h"][0])        
        extent = YX(h, w) * simulator.survey.scaling
        scan_step = float(scan_step_input.value)
        scan_shape = (extent / scan_step).to_int()
        dwell_time = float(dwell_time_input.value) * 1e-6
        scan_time = np.prod(scan_shape) * dwell_time * int(sum_stack_input.value)
        return stub + f"""

- Shape: {scan_shape[0]} x {scan_shape[1]} px
- Extent: {extent[0]:.1f} x {extent[1]:.1f} nm
- Duration {humanize.naturaldelta(scan_time, minimum_unit="microseconds")}
"""

    scan_info_md = pn.pane.Markdown(
        object=scan_info_str()
    )

    def _update_md(*e):
        scan_info_md.object = scan_info_str()

    def _update_md_bk(attr, old, new):
        scan_info_md.object = scan_info_str()

    scan_step_input.param.watch(_update_md, "value")
    dwell_time_input.param.watch(_update_md, "value")
    sum_stack_input.param.watch(_update_md, "value")
    rectangles.cds.on_change("data", _update_md_bk)

    def reset_drift(*e, copy_correction=True):
        drift_estimator.reset()
        if copy_correction:
            if len(corrected_rectangles.cds.data["cx"]) > 0:
                rectangles.cds.data.update(
                    **corrected_rectangles.cds.data,
                )
        corrected_rectangles.clear()
        drift_info_md.object = "No drift information"

    def _clear_corrected(attr, old, new):
        reset_drift(copy_correction=False)

    rectangles.cds.on_change("data", _clear_corrected)

    def reset_if_false(e):
        if not e.new:
            reset_drift()

    estimate_drift_button.param.watch(reset_if_false, "value")

    reset_drift_btn = pn.widgets.Button(
        name="Reset drift history",
        button_type="warning",
        width_policy="max",
    )
    reset_drift_btn.on_click(reset_drift)

    tabs_left = pn.Tabs(
        ('Survey', survey_fig.layout),
        closable=False,
        dynamic=False,
    )

    tabs_right = pn.Tabs(
        ('Scan', scan_fig.layout),
        ('Drift', drift_fig_pane),
        closable=False,
        dynamic=False,
    )

    doc_md = pn.pane.Markdown(
        object="""# STEM Imaging Simulator

Use the controls in the sidebar to launch STEM scans with the displayed parameters

## Survey

The "Survey" scan gives a fixed size overview of the sample
- A "Live" survey automatically re-scans every 1-2 seconds

## Scan

A true scan area can be defined using a scan ROI drawn on the survey image
- Right-click the image and select the first "Box Edit Tool" in the dropdown menu
- Long-press the image to start drawing an ROI, long-press again to stop drawing
- To adjust an ROI it is necessary to select the tool again, then drag or re-draw it

Scans parameters are displayed in the sidebar, note that a scan takes the real amount of time displayed plus additional overhead.

## Drift

The microscope suffers from stage drift, but is equipped with drift correction
- Use the second "Box Edit Tool" to define a fixed wide-field drift estimation ROI
- Enable drift estimation in the sidebar
- Each new survey image will update the drift model
- View the behaviour of the estimation in the "Drift" tab of the right plot
- The correction is applied to the Scan according to the toggle
- Reset the drift history if the estimation diverges
- Adjusting the Drift ROI or Scan ROI resets the drift estimation

With drift estimation enabled it should be possible to take a reasonably sharp stacked Scan.
"""
    )
    modal_btn = pn.widgets.Button(
        name="Help",
        button_type="primary",
        width_policy="max",
    )

    layout = pn.template.BootstrapTemplate(
        title="STEM Image Simulator",
        sidebar=[
            modal_btn,
            pn.pane.Markdown(object="## Survey"),
            pn.Row(
                live_survey_button,
                single_survey,
                survey_spinner,
                width_policy="max",
            ),
            pn.pane.Markdown(object=f"""
- Shape: {simulator.survey.shape[0]} x {simulator.survey.shape[1]} px
- Extent: {simulator.survey.extent[0]:.0f} x {simulator.survey.extent[1]:.0f} nm
- Dwell time: {humanize.naturaldelta(survey_dwell_time, minimum_unit='microseconds')}
- Duration {humanize.naturaldelta(survey_dwell_time * np.prod(simulator.survey.shape), minimum_unit='microseconds')}

## Scan"""),
            scan_step_input,
            dwell_time_input,
            sum_stack_input,
            pn.Row(
                scan_button,
                scan_spinner,
                width_policy="max",
            ),
            scan_info_md,
            pn.pane.Markdown(object="## Drift correction"),
            estimate_drift_button,
            estimate_correction_button,
            reset_drift_btn,
            drift_info_md,
        ],
        main=[
            pn.Row(
                tabs_left,
                tabs_right,
            ),
        ],
        modal=[doc_md],
    )
    modal_btn.on_click(lambda e: layout.open_modal())
    return layout
