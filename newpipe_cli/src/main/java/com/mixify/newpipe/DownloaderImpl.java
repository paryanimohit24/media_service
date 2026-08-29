package com.mixify.newpipe;

import org.schabi.newpipe.extractor.downloader.Downloader;
import org.schabi.newpipe.extractor.downloader.Request;
import org.schabi.newpipe.extractor.downloader.Response;
import org.schabi.newpipe.extractor.exceptions.ReCaptchaException;

import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

import okhttp3.RequestBody;
import okhttp3.ResponseBody;

public final class DownloaderImpl extends Downloader {
    private static final String USER_AGENT =
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0";

    private final okhttp3.OkHttpClient client;

    public DownloaderImpl() {
        this.client = new okhttp3.OkHttpClient.Builder()
                .readTimeout(45, TimeUnit.SECONDS)
                .connectTimeout(20, TimeUnit.SECONDS)
                .build();
    }

    @Override
    public Response execute(Request request) throws IOException, ReCaptchaException {
        final String httpMethod = request.httpMethod();
        final String url = request.url();
        final Map<String, List<String>> headers = request.headers();
        final byte[] dataToSend = request.dataToSend();

        RequestBody requestBody = null;
        if (dataToSend != null) {
            requestBody = RequestBody.create(dataToSend);
        }

        final okhttp3.Request.Builder requestBuilder = new okhttp3.Request.Builder()
                .method(httpMethod, requestBody)
                .url(url)
                .addHeader("User-Agent", USER_AGENT);

        headers.forEach((headerName, headerValueList) -> {
            requestBuilder.removeHeader(headerName);
            for (String headerValue : headerValueList) {
                requestBuilder.addHeader(headerName, headerValue);
            }
        });

        try (okhttp3.Response response = client.newCall(requestBuilder.build()).execute()) {
            if (response.code() == 429) {
                throw new ReCaptchaException("reCaptcha Challenge requested", url);
            }

            String responseBodyToReturn = null;
            try (ResponseBody body = response.body()) {
                if (body != null) {
                    responseBodyToReturn = body.string();
                }
            }

            final String latestUrl = response.request().url().toString();
            return new Response(
                    response.code(),
                    response.message(),
                    response.headers().toMultimap(),
                    responseBodyToReturn,
                    latestUrl
            );
        }
    }
}
