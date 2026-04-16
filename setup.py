"""
CNC 시뮬레이터 패키지 설치 설정
"""
from setuptools import setup, find_packages

setup(
    name="cnc-simulator",
    version="0.1.0",
    description="CNC 가공 시뮬레이션 및 NC 코드 검증 도구",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="OpenCNC",
    python_requires=">=3.9",
    packages=find_packages(),
    install_requires=[
        "PySide6>=6.5.0",
        "numpy>=1.24.0",
        "scipy>=1.10.0",
        "PyOpenGL>=3.1.7",
        "pyqtgraph>=0.13.0",
        "pyyaml>=6.0",
        "trimesh>=3.21.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.4.0",
            "pytest-cov>=4.0.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "cnc-simulator=app.main:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Manufacturing",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Scientific/Engineering",
    ],
)
