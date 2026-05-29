FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

# Copy tất cả file xlsx vào thư mục /app/data/
RUN mkdir -p /app/data
COPY data/ /app/data/

EXPOSE 8080

CMD ["python", "bot.py"]
