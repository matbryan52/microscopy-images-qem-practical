import pathlib
import numpy as np
import qem_practical
from qem_practical.simulator import STEMImageSimulator
from qem_practical.simulator_ui import simulator_ui
rootdir = pathlib.Path(qem_practical.__file__).parent.parent.parent

sim_data = np.load(rootdir / "data" / "particles.npz")
image = sim_data["data"]
extent = sim_data["extent"]
simulator = STEMImageSimulator(**sim_data)
simulator_ui(simulator).show("stem-simulator")
