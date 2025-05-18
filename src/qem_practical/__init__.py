import os
import pathlib
import tempfile


DATA_NAME = "qem_particles.npz"
DATA_PATH = pathlib.Path(os.getcwd()) / DATA_NAME
try:
    tempdir = pathlib.Path(tempfile.gettempdir())
    assert tempdir.is_dir()
    DATA_PATH = tempdir / DATA_NAME
except (AssertionError, ValueError, TypeError):
    pass


def download_data():
    import tqdm.auto as tqdm
    import requests

    url = (
        R"https://github.com/matbryan52/microscopy-images-qem-practical"
        R"/releases/download/data/particles.npz"
    )
    response = requests.get(url, stream=True)

    with open(DATA_PATH, "wb") as handle:
        for data in tqdm.tqdm(
            response.iter_content(chunk_size=1024 * 32),
            desc="Downloading data (~13 MB)",
        ):
            handle.write(data)
