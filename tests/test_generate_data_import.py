import subprocess
import sys


def test_synthetic_generator_import_does_not_start_training_or_plotting():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "from ml_training.generate_data import generate_synthetic_ami_data; "
                "assert callable(generate_synthetic_ami_data); "
                "assert 'matplotlib.pyplot' not in sys.modules; "
                "assert 'sklearn' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
