FROM python:3.13-slim

# lxml and xmlsec are pinned to versions with prebuilt wheels that were tested together
# for XML signature verification (python3-saml). No compiler needed.
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
EXPOSE 5000
CMD ["gunicorn", "-b", "0.0.0.0:5000", "-w", "1", "--threads", "4", "--access-logfile", "-", "run:app"]
