FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
LABEL org.ashvane.supervisor.policy="1"
ENV PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
RUN apt-get update && apt-get install --no-install-recommends -y ffmpeg libgomp1 libsndfile1 espeak-ng && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /opt/ashvane/requirements.txt
RUN python -m pip install --no-cache-dir -r /opt/ashvane/requirements.txt
COPY runner.py /opt/ashvane/runner.py
USER 65534:65534
WORKDIR /tmp
ENTRYPOINT ["/usr/local/bin/python", "-I", "/opt/ashvane/runner.py"]
