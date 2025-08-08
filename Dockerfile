# syntax=docker/dockerfile:1.3
FROM python:3.11-bullseye

COPY requirements.txt requirements.txt

RUN apt-get update \
    && apt-get install -y pandoc calibre \
    && pip3 install -r requirements.txt

COPY src/ src/
COPY ./morss.py /usr/local/lib/python3.8/site-packages/morss/

CMD ["python3", "src/news2kindle.py"]
