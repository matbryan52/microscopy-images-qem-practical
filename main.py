from qem_practical.simulator import STEMImageSimulator
from qem_practical.simulator_ui import simulator_ui

simulator = STEMImageSimulator.default()
simulator_ui(simulator).show("stem-simulator")
