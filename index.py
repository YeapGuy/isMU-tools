import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SCRIPTS = {
    "monitor": BASE_DIR / "monitor.py",
    "group": BASE_DIR / "group_signup.py",
}
ENV_KEY = "IS_TOOL_MODE"


def resolve_target():
    env_choice = os.getenv(ENV_KEY, "").strip().lower()
    if env_choice:
        if env_choice in SCRIPTS:
            print(f"Environment variable {ENV_KEY} set to '{env_choice}', launching matching script...")
            return SCRIPTS[env_choice]
        print(f"Value '{env_choice}' for {ENV_KEY} is not supported. Please use one of: {', '.join(SCRIPTS)}.")

    prompt = ("Choose a script to run\n"
              "1. monitor.py\n"
              "2. group_signup.py\n"
              "Selection (1 or 2): ")

    while True:
        choice = input(prompt).strip()
        if choice == "1":
            return SCRIPTS["monitor"]
        if choice == "2":
            return SCRIPTS["group"]
        print("Invalid selection, try again.")


def main():
    target = resolve_target()
    print(f"Launching {target.name}...")
    result = subprocess.run([sys.executable, str(target)])
    if result.returncode != 0:
        print(f"{target.name} exited with code {result.returncode}.")


if __name__ == "__main__":
    main()
