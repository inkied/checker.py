# Use official lightweight Python image
FROM python:3.11-slim

# Set working directory inside container
WORKDIR /app

# Copy project files
COPY . .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose port (not mandatory if your script doesn't serve HTTP)
# EXPOSE 8080

# Run the checker script on container start
CMD ["python", "checker.py"]
