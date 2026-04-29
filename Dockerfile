FROM python:3.12-slim

WORKDIR /app

# Install dependencies in a separate layer so rebuilds are fast when only
# source code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "gmail_poller.py"]
