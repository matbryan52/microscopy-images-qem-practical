from qem_practical.simulator import STEMImageSimulator

simulator = STEMImageSimulator.default(drift_speed="random")
survey_image = simulator.survey_image(1e-5)
survey_image.plot()
