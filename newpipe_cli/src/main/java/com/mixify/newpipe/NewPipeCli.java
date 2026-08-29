package com.mixify.newpipe;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import org.schabi.newpipe.extractor.NewPipe;
import org.schabi.newpipe.extractor.stream.AudioStream;
import org.schabi.newpipe.extractor.stream.StreamInfo;
import org.schabi.newpipe.extractor.stream.StreamType;
import org.schabi.newpipe.extractor.stream.VideoStream;

import java.util.Comparator;
import java.util.List;

public final class NewPipeCli {
    private static final Gson GSON = new Gson();

    public static void main(String[] args) {
        if (args.length < 1 || args[0].isBlank()) {
            System.err.println("Usage: newpipe-cli <url>");
            System.exit(2);
        }

        final String url = args[0].trim();
        try {
            NewPipe.init(new DownloaderImpl());
            StreamInfo info = StreamInfo.getInfo(url);

            if (info.getStreamType() != StreamType.VIDEO_STREAM) {
                throw new IllegalStateException("URL is not a video stream.");
            }

            String mediaUrl = null;
            boolean audioOnly = false;

            List<AudioStream> audioStreams = info.getAudioStreams();
            if (audioStreams != null && !audioStreams.isEmpty()) {
                AudioStream best = audioStreams.stream()
                        .max(Comparator.comparingInt(AudioStream::getAverageBitrate))
                        .orElse(audioStreams.get(0));
                mediaUrl = best.getContent();
                audioOnly = true;
            }

            if (mediaUrl == null) {
                List<VideoStream> videoStreams = info.getVideoStreams();
                if (videoStreams != null && !videoStreams.isEmpty()) {
                    VideoStream best = videoStreams.stream()
                            .max(Comparator.comparing(VideoStream::getItag))
                            .orElse(videoStreams.get(0));
                    mediaUrl = best.getContent();
                    audioOnly = false;
                }
            }

            if (mediaUrl == null || mediaUrl.isBlank()) {
                throw new IllegalStateException("No playable audio/video stream found.");
            }

            JsonObject out = new JsonObject();
            out.addProperty("title", info.getName());
            out.addProperty("media_url", mediaUrl);
            out.addProperty("audio_only", audioOnly);
            out.addProperty("extractor", "newpipe");
            System.out.println(GSON.toJson(out));
        } catch (Exception e) {
            System.err.println(e.getMessage() != null ? e.getMessage() : e.toString());
            System.exit(1);
        }
    }
}
