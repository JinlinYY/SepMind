"""Setup file for pha package installation."""

from setuptools import setup, find_packages

with open("README.md", mode="r", encoding="utf-8") as readme_file:
    readme = readme_file.read()



setup(
      name="pha",
      version="0.0.1",
      author="Akshay Paruchuri, Ali Heydari, Xuhai 'Orson' Xu",
      author_email="aliheydari@google.com",
      description="Expert-guided preliminary chemical separation design, derived from Google Health PHA",
      long_description=readme,
      long_description_content_type="text/markdown",
      license="Apache-2.0",
      url="https://github.com/google-health/consumer-health-research/tree/main/personal_health_agent",
      download_url="https://github.com/google-health/consumer-health-research/tree/main/personal_health_agent",
      packages=find_packages(include=["pha", "pha.*", "api", "api.*", "separation", "separation.*"]),
      classifiers=[
                   "Development Status :: 4 - Beta",
                   "Intended Audience :: Science/Research",
                   "Programming Language :: Python :: 3.12",
                   "Topic :: Scientific/Engineering :: Artificial Intelligence"
                   ],
      keywords=("Separation Design", "Expert-guided Agents", "Chemical Engineering")
      )
