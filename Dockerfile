FROM eclipse-temurin:21-jdk AS java-build
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends maven \
    && rm -rf /var/lib/apt/lists/*
COPY newpipe_cli/pom.xml ./pom.xml
COPY newpipe_cli/src ./src
RUN mvn -q -DskipTests package && cp target/newpipe-cli-1.0.0.jar /build/newpipe-cli.jar

FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl ca-certificates unzip openjdk-21-jre-headless \
    && curl -fsSL https://deno.land/install.sh | sh \
    && mv /root/.deno/bin/deno /usr/local/bin/deno \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=java-build /build/newpipe-cli.jar /app/newpipe-cli.jar

EXPOSE 8001
ENV PORT=8001
ENV NEWPIPE_CLI_JAR=/app/newpipe-cli.jar
ENV USE_NEWPIPE_EXTRACTOR=true

CMD uvicorn app:app --host 0.0.0.0 --port ${PORT} --workers 1
