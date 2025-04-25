import pathlib
import shutil
import qem_practical
rootdir = pathlib.Path(qem_practical.__file__).parent.parent.parent
import subprocess


def update():
    print(f"Updating from {rootdir}")
    output = subprocess.check_output(
        ['git', 'pull', "--ff-only"],
        cwd=rootdir,
        shell=True,
    )
    print(output.decode('utf-8'))

    output = subprocess.check_output(
        ['uv', 'pip', "install", "-e", "."],
        cwd=rootdir,
        shell=True,
    )
    print(output.decode('utf-8'))

    shutil.copyfile(
        rootdir / "main.py",
        rootdir.parent / "Workspace" / "main.py",
    )
