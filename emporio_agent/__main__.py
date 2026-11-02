import sys

try:
    from .cli import main
except ModuleNotFoundError as exc:  # most often: the virtual environment is not active
    sys.exit(
        f"Missing dependency '{exc.name}'. Activate the virtual environment and install the requirements:\n"
        "  Windows:      .venv\\Scripts\\Activate.ps1   (or run .venv\\Scripts\\python -m emporio_agent)\n"
        "  Linux/macOS:  source .venv/bin/activate\n"
        "  then:         pip install -r requirements.txt"
    )

sys.exit(main())
