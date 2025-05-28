FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV DOWNLOAD_DIR=/downloads
ENV CACHE_DIR=/cache
VOLUME ["/downloads","/cache"]
CMD ["python", "tik.py"]