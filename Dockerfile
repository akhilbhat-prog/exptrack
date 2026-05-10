FROM python:3.12-slim

WORKDIR /app

# Install dependencies in a separate layer so rebuilds are fast when only
# source code changes.
COPY requirements.txt .
COPY categorizer/requirements.txt categorizer/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r categorizer/requirements.txt

COPY . .

EXPOSE 8080

CMD ["python", "loader/gmail_poller.py"]
