from setuptools import setup, find_packages

setup(
    name="hamiltonian_swarm",
    version="0.1.0",
    description="Physics-informed multi-agent AI framework with QPSO and Hamiltonian mechanics",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "torch>=2.1.0",
        "numpy>=1.24.0",
        "scipy>=1.11.0",
        "matplotlib>=3.7.0",
        "networkx>=3.1",
        "tqdm>=4.65.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.4.0",
        ],
    },
)
