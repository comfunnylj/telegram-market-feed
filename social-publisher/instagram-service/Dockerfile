FROM python:3.12-slim
WORKDIR /app
COPY instagram_publisher.py /app/instagram_publisher.py
RUN mkdir /data && chown 65532:65532 /data
ENV PYTHONUNBUFFERED=1
USER 65532:65532
CMD ["python", "-u", "/app/instagram_publisher.py"]
