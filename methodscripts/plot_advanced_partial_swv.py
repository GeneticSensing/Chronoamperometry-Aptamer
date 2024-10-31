#!/usr/bin/env python3
"""
Spin-off from PalmSens advanced SWV MethodSCRIPT example (plot_advanced_swv.py)

This script keeps a tally of scans. Every 10 scans including the first scan,
a calibration scan is performed, which is just a full SWV scan.

Calibration scans are used to determine partial SWV scanning windows for the
baseline and peak, which is computed with scipy. Scanning windows are 30mV.

When the experiement is completed, i.e. all scans are completed, the number
of scans needs to be manually reset to 0.
"""

# Standard library imports
import csv
import datetime
import json
import logging
import os
import os.path
import sys
import typing

# Third-party imports
import matplotlib.pyplot as plt
import numpy as np
import scipy.signal as sg

# Local imports
import palmsens.instrument
import palmsens.mscript
import palmsens.serial


### Start of configuration

LOG = logging.getLogger(__name__)

# COM port of the device (None = auto detect).
DEVICE_PORT = None

# Location of MethodSCRIPT file to use.
SWV_ESPICO_PATH = 'scripts/swv_espico.mscr'
PARTIAL_SWV_ESPICO_TEMPLATE_PATH = 'scripts/partial_swv_espico_template.mscr'
PARTIAL_SWV_ESPICO_PATH = 'scripts/partial_swv_espico.mscr'

# Location of output files. Directory will be created if it does not exist.
OUTPUT_PATH = 'output'

# Column names.
COLUMN_NAMES = ['Potential', 'Current', 'Forward Current', 'Reverse Current']
# Index of column to put on the x axis.
XAXIS_COLUMN_INDEX = 0
# Indices of columns to put on the y axis. The variables must be same type.
YAXIS_COLUMN_INDICES = [1, 2, 3]

### End of configuration

def write_curves_to_csv(file: typing.IO, curves: list[list[list[palmsens.mscript.MScriptVar]]]):
    """Write the curves to file in CSV format.

    `file` must be a file-like object in text mode with newlines translation
    disabled.

    The header row is based on the first row of the first curve. It is assumed
    that all rows in all curves have the same data types.

    MS Excel Compatible
    """
    file.write('sep=;\n')
    writer = csv.writer(file, delimiter=';')
    for curve in curves:
        # Write header row.
        writer.writerow([f'{value.type.name} [{value.type.unit}]' for value in curve[0]])
        # Write data rows.
        for package in curve:
            writer.writerow([value.value for value in package])


def configure_logging():
    logging.basicConfig(level=logging.DEBUG, format='[%(module)s] %(message)s',
                        stream=sys.stdout)
    # Uncomment the following line to reduce the log level of our library.
    # logging.getLogger('palmsens').setLevel(logging.INFO)
    # Disable excessive logging from matplotlib.
    logging.getLogger('matplotlib').setLevel(logging.INFO)
    logging.getLogger('PIL.PngImagePlugin').setLevel(logging.INFO)


def load_json(file_path: str) -> dict:
    with open(file_path, "r") as f:
        return json.load(f)
    

def save_json(data: dict, file_path: str):
    with open(file_path, "w") as f:
        json.dump(data, f, indent=4)


def create_output_path(base_name: str):
    base_path = os.path.join(OUTPUT_PATH, base_name)
    os.makedirs(OUTPUT_PATH, exist_ok=True)
    return base_path


def update_method_script(template_path: str, dest_path: str, replacements: dict):
    with open(template_path, "r") as f:
        content = f.read()
    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value)
    with open(dest_path, "w", newline='\n') as f:
        f.write(content)
    

class ScanTracker:
    """
    Scan tracking data is persisted in scan_tracker.json
    
    Everytime an experiment completes, i.e. all scans completes, num_scans must be manually reset to 0
    """
    def __init__(self, file_path="scan_tracker.json"):
        self.file_path = file_path
        self.data = load_json(file_path)

    def increment_scan(self):
        self.data["num_scans"] += 1
        save_json(self.data, self.file_path)

    def is_calibration_scan(self):
        return self.data["num_scans"] % 10 == 0

    def update_peak_values(self, xvalues, yvalues):
        trunc_xvalues = xvalues[100:]
        trunc_yvalues = yvalues[100:]
        prominence_threshold = 0.0000005
        distance_threshold = 100
        peaks, properties = sg.find_peaks(trunc_yvalues, prominence=prominence_threshold, distance=distance_threshold)
        if len(peaks) == 0:
            print("No peaks found!")
            return
        if len(peaks) > 1:
            print("More than one peak found!")
        self.data["peak"] = trunc_xvalues[peaks[0]]
        self.data["left_baseline"] = trunc_xvalues[properties['left_bases'][0]]
        save_json(self.data, self.file_path)

    def get_replacements(self):
        left_baseline = self.data["left_baseline"]
        peak = self.data["peak"]
        # Determine scanning windows
        return {
            "<E_begin_baseline>": f"{int(left_baseline*1000) - 30}m",
            "<E_end_baseline>": f"{int(left_baseline*1000)}m",
            "<E_begin_peak>": f"{int(peak*1000) - 15}m",
            "<E_end_peak>": f"{int(peak*1000) + 15}m"
        }


def plot_curves(curves: list[list[list[palmsens.mscript.MScriptVar]]], base_path: str, scan_tracker: ScanTracker=None, partial=False):
    """
    Plots curves. If 'partial' is True, the plot will separate baseline and peak segments.
    """
    plt.figure()
    plt.title(base_path)

    # Configure the X and Y axis labels
    xvar = curves[0][0][XAXIS_COLUMN_INDEX]
    plt.xlabel(f'{xvar.type.name} [{xvar.type.unit}]')

    yvar = curves[0][0][YAXIS_COLUMN_INDICES[0]]
    plt.ylabel(f'{yvar.type.name} [{yvar.type.unit}]')

    plt.grid(visible=True, which='major', linestyle='-')
    plt.grid(visible=True, which='minor', linestyle='--', alpha=0.2)
    plt.minorticks_on()

    color_cycle = plt.rcParams['axes.prop_cycle'].by_key()['color']

    # Loop through all curves
    print(len(curves))
    for icurve, curve in enumerate(curves):
        xvalues = palmsens.mscript.get_values_by_column(curves, XAXIS_COLUMN_INDEX, icurve)

        for iy_axis, y_axis in enumerate(YAXIS_COLUMN_INDICES):
            yvalues = palmsens.mscript.get_values_by_column(curves, y_axis, icurve)

            if curve[0][y_axis].type != yvar.type:
                continue

            # Create a label for each curve
            label = f'{COLUMN_NAMES[y_axis]} vs {COLUMN_NAMES[XAXIS_COLUMN_INDEX]}'
            if len(curves) > 1:
                label += ' cell ' + ('off' if icurve % 2 == 0 else 'on')
                label += ' (baseline)' if icurve < 2 else ' (peak)'

            # Handle partial plot (two segments)
            if partial:
                # Associated baseline and peak curves have same colour
                color = color_cycle[((icurve * len(YAXIS_COLUMN_INDICES) + iy_axis) % (len(YAXIS_COLUMN_INDICES) * 2)) % len(color_cycle)]
                plt.plot(xvalues, yvalues, color=color, label=label)
            else:
                # Standard single plot for calibration
                plt.plot(xvalues, yvalues, label=label)
                # Determine peak and baseline for subsequent partial scans
                if icurve == 1 and iy_axis == 0:
                    scan_tracker.update_peak_values(xvalues, yvalues)

    # Display the legend and save the plot
    plt.legend()
    plt.savefig(base_path + '.png')
    plt.show()


def perform_scan(script_path: str, scan_tracker: ScanTracker, partial=False):
    LOG.info("Starting " + ("partial" if partial else "calibration") + " SWV scan.")
    base_path = create_output_path(datetime.datetime.now().strftime('ms_plot_swv_%Y%m%d-%H%M%S'))

    port = DEVICE_PORT
    if port is None:
        port = palmsens.serial.auto_detect_port()

    # Create and open serial connection to the device.
    with palmsens.serial.Serial(port, 1) as comm:
        device = palmsens.instrument.Instrument(comm)
        device_type = device.get_device_type()
        if device_type != palmsens.instrument.DeviceType.EMSTAT_PICO:
            self.comm.close()
            raise RuntimeError("Device is not an Emstat Pico")
        LOG.info('Connected to %s.', device_type)

        # Read and send the MethodSCRIPT file.
        LOG.info('Sending MethodSCRIPT.')
        device.send_script(script_path)

        # Read the result lines.
        LOG.info('Waiting for results.')
        result_lines = device.readlines_until_end()

    os.makedirs(OUTPUT_PATH, exist_ok=True)
    with open(base_path + '.txt', 'wt', encoding='ascii') as file:
        file.writelines(result_lines)

    # Parse the result.
    curves = palmsens.mscript.parse_result_lines(result_lines)

    with open(base_path + '.csv', 'wt', newline='') as f:
        write_curves_to_csv(f, curves)

    # Call plot_curves with the partial flag
    plot_curves(curves, base_path, scan_tracker=scan_tracker, partial=partial)
    scan_tracker.increment_scan()


def main():
    configure_logging()
    scan_tracker = ScanTracker()

    if scan_tracker.is_calibration_scan():
        perform_scan(SWV_ESPICO_PATH, scan_tracker)
    else:
        replacements = scan_tracker.get_replacements()
        update_method_script(PARTIAL_SWV_ESPICO_TEMPLATE_PATH, PARTIAL_SWV_ESPICO_PATH, replacements)
        perform_scan(PARTIAL_SWV_ESPICO_PATH, scan_tracker, partial=True)


if __name__ == '__main__':
    main()