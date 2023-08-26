FROM python:3.11 as py

FROM py as build

RUN apt update && apt install -y g++ git
COPY requirements.txt /
RUN pip install --prefix=/inst -U -r /requirements.txt

FROM py

COPY --from=build /inst /usr/local

WORKDIR /website
CMD ["python", "src"]
COPY . /website