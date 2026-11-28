package os.opos.launcher;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.Proxy;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Calls only the phone-local OPOS AI page and its JSON API. */
final class AiClient {
    private static final String BASE = "http://127.0.0.1:8765";
    private static final Pattern TOKEN = Pattern.compile("<meta\\s+name=\"opos-token\"\\s+content=\"([A-Za-z0-9_-]+)\"");
    // The phone-local snapshot may include the lead panes plus optional model lanes.
    private static final int MAX_RESPONSE = 8 * 1024 * 1024;
    private String token;

    static final class ApiException extends IOException {
        final int status;

        ApiException(int status, String message) {
            super(message);
            this.status = status;
        }
    }

    JSONObject getSnapshot() throws IOException, JSONException {
        return api("GET", null);
    }

    JSONObject post(JSONObject body) throws IOException, JSONException {
        return api("POST", body);
    }

    private JSONObject api(String method, JSONObject body) throws IOException, JSONException {
        if (token == null) refreshToken();
        try {
            return new JSONObject(request(method, "/api/ai", token, body));
        } catch (ApiException stale) {
            if (stale.status != 403) throw stale;
            refreshToken();
            return new JSONObject(request(method, "/api/ai", token, body));
        }
    }

    private void refreshToken() throws IOException {
        token = null;
        Matcher match = TOKEN.matcher(request("GET", "/ai", null, null));
        if (!match.find()) throw new IOException("AI page token unavailable");
        token = match.group(1);
    }

    private static String request(String method, String path, String sessionToken, JSONObject body)
            throws IOException {
        // Paths are fixed here; redirects are never followed to another address.
        HttpURLConnection connection = (HttpURLConnection) new URL(BASE + path).openConnection(Proxy.NO_PROXY);
        try {
            connection.setInstanceFollowRedirects(false);
            connection.setUseCaches(false);
            connection.setConnectTimeout(2000);
            connection.setReadTimeout(8000);
            connection.setRequestMethod(method);
            connection.setRequestProperty("Accept", path.equals("/ai") ? "text/html" : "application/json");
            if (sessionToken != null) connection.setRequestProperty("X-OPOS-Token", sessionToken);
            if (body != null) {
                byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
                connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                connection.setRequestProperty("Origin", BASE);
                connection.setFixedLengthStreamingMode(bytes.length);
                try (OutputStream output = connection.getOutputStream()) {
                    output.write(bytes);
                }
            }
            int status = connection.getResponseCode();
            InputStream stream = status >= 400 ? connection.getErrorStream() : connection.getInputStream();
            String response = read(stream);
            if (status != 200) {
                String message = "The phone could not complete that action.";
                try {
                    message = new JSONObject(response).optString("error", message);
                } catch (JSONException ignored) {
                    // Status, not an arbitrary HTML error page, decides the result.
                }
                throw new ApiException(status, message);
            }
            return response;
        } finally {
            connection.disconnect();
        }
    }

    private static String read(InputStream input) throws IOException {
        if (input == null) return "";
        try (InputStream stream = input; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] chunk = new byte[8192];
            int size;
            while ((size = stream.read(chunk)) != -1) {
                if (output.size() + size > MAX_RESPONSE) throw new IOException("Phone response too large");
                output.write(chunk, 0, size);
            }
            return new String(output.toByteArray(), StandardCharsets.UTF_8);
        }
    }
}
