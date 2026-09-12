"""
EdgeRTOS package setup.
Installs the EdgeRTOS scheduling library as a proper Python package,
removing the need for sys.path hacks in example scripts.

Usage:
    pip install -e .          # Editable install for development
    pip install .             # Standard install
"""

from setuptools import setup, find_packages

setup(
    name="edgertos",
    version="1.0.0",
    description=(
        "Confidence-Aware Real-Time Scheduling Layer for Edge AI Inference. "
        "Designed for Raspberry Pi 4/5 (Ubuntu 22.04+) and cross-platform development."
    ),
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    authors=[
        {"name": "Atharv Huilgol"},
        {"name": "Vibhuti Sahu"},
        {"name": "Chinmayi Pethkar"},
    ],
    license="MIT",
    python_requires=">=3.9",
    packages=find_packages(exclude=["tests*", "benchmarks*", "docs*"]),
    install_requires=[
        "psutil>=5.9.0",
    ],
    extras_require={
        "rpi": [
            "RPi.GPIO>=0.7.1",
            "smbus2>=0.4.2",
            "pi-ina219>=1.4.0",
            "ai-edge-litert>=1.0.1",
        ],
        "dev": [
            "pytest>=7.4.0",
            "numpy>=1.24.0",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: POSIX :: Linux",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: MacOS",
        "Topic :: System :: Real-time",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Intended Audience :: Education",
    ],
)
