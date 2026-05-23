FROM python:3.12-slim

WORKDIR /app

# libgomp1 is the GNU OpenMP runtime required by LightGBM and scikit-learn;
# not bundled in their PyPI wheels on Linux.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies in a separate layer so rebuilds are fast when only
# source code changes.
COPY requirements.txt .
COPY categorizer/requirements.txt categorizer/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r categorizer/requirements.txt

COPY . .

EXPOSE 8080

CMD ["python", "loader/app.py"]
