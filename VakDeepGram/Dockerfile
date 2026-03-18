FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    portaudio19-dev \
    curl \
    swig \
    libspeexdsp-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Ensure Python can import the package (app lives in src/vakdeepgram/)
ENV PYTHONPATH=/app/src

# Expose port
EXPOSE 8080

# Run the application via the package entrypoint (vakdeepgram.main runs uvicorn in __main__)
CMD ["python", "-m", "vakdeepgram.main"]
