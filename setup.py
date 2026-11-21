"""Setup file for sepmind package installation."""

from setuptools import setup, find_packages

with open("README.md", mode="r", encoding="utf-8") as readme_file:
    readme = readme_file.read()



setup(
      name="sepmind",
      version="0.2.0",
      author="SepMind contributors",
      description="Expert-guided agent framework for chemical separation process design",
      long_description=readme,
      long_description_content_type="text/markdown",
      license="Apache-2.0",
      url="https://github.com/JinlinYY/SepMind",
      download_url="https://github.com/JinlinYY/SepMind",
      packages=find_packages(include=["sepmind", "sepmind.*", "api", "api.*"]),
      classifiers=[
                   "Development Status :: 4 - Beta",
                   "Intended Audience :: Science/Research",
                   "Programming Language :: Python :: 3.12",
                   "Topic :: Scientific/Engineering :: Artificial Intelligence"
                   ],
      keywords=("Separation Design", "Expert-guided Agents", "Chemical Engineering")
      )
