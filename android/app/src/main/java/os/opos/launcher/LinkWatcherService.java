package os.opos.launcher;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class LinkWatcherService extends Service {
    private static final String USB_STATE = "android.hardware.usb.action.USB_STATE";
    static final String ACTION_CABLE_CHANGED = "os.opos.launcher.action.CABLE_CHANGED";
    static final String EXTRA_CONNECTED = "connected";
    private static final String WATCH_CHANNEL = "usb_watcher";
    // Keep the existing high-importance channel for pairing requests only.
    private static final String PAIRING_CHANNEL = "gpu_link";
    private static final String CABLE_CHANNEL = "gpu_link_cable";
    private static final int WATCH_ID = 1;
    static final int LINK_ID = 2;
    private static final int PAIRING_ID = 3;
    private static final long POLL_DELAY_MS = 2000;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ExecutorService network = Executors.newSingleThreadExecutor();
    private final AiClient client = new AiClient();
    private final Runnable poll = this::refreshPairing;
    private boolean announced;
    private boolean destroyed;
    private boolean polling;
    private Boolean lastConnected;
    private String notifiedCode;
    private String notifiedLabel;
    private NotificationManager notifications;

    static void start(Context context) {
        try {
            context.startForegroundService(new Intent(context, LinkWatcherService.class));
        } catch (IllegalStateException | SecurityException restricted) {
            // A restricted boot or background start can be retried from the visible activity.
        }
    }

    private Intent readUsbState() {
        return registerReceiver(null, new IntentFilter(USB_STATE));
    }

    static Boolean cableConnected(Context context) {
        Intent state = context.registerReceiver(null, new IntentFilter(USB_STATE));
        return state == null || !state.hasExtra(EXTRA_CONNECTED)
                ? null : state.getBooleanExtra(EXTRA_CONNECTED, false);
    }

    private final BroadcastReceiver receiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            if (USB_STATE.equals(intent.getAction())) {
                updateConnection(intent);
            } else {
                // AC, wireless and power-only chargers also produce power broadcasts.
                updateConnection(readUsbState());
            }
        }
    };

    @Override
    public void onCreate() {
        super.onCreate();
        notifications = getSystemService(NotificationManager.class);
        notifications.createNotificationChannel(new NotificationChannel(WATCH_CHANNEL,
                getString(R.string.watcher_channel), NotificationManager.IMPORTANCE_LOW));
        notifications.createNotificationChannel(new NotificationChannel(PAIRING_CHANNEL,
                getString(R.string.link_title), NotificationManager.IMPORTANCE_HIGH));
        notifications.createNotificationChannel(new NotificationChannel(CABLE_CHANNEL,
                getString(R.string.cable_channel), NotificationManager.IMPORTANCE_LOW));
        // Remove a cable alert left on the former shared high-importance channel.
        notifications.cancel(LINK_ID);
        // A killed service may leave a pairing notification from an expired request.
        notifications.cancel(PAIRING_ID);

        PendingIntent home = PendingIntent.getActivity(this, WATCH_ID,
                new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE);
        Notification ready = new Notification.Builder(this, WATCH_CHANNEL)
                .setSmallIcon(R.drawable.ic_status).setContentTitle(getText(R.string.ready))
                .setContentIntent(home).setOngoing(true).setShowWhen(false).build();
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(WATCH_ID, ready, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        } else {
            startForeground(WATCH_ID, ready);
        }

        IntentFilter filter = new IntentFilter(USB_STATE);
        filter.addAction(Intent.ACTION_POWER_CONNECTED);
        filter.addAction(Intent.ACTION_POWER_DISCONNECTED);
        if (Build.VERSION.SDK_INT >= 33) {
            registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED);
        } else {
            registerReceiver(receiver, filter);
        }
    }

    private void updateConnection(Intent usb) {
        if (usb == null || !usb.hasExtra(EXTRA_CONNECTED)) return;
        boolean connected = usb.getBooleanExtra(EXTRA_CONNECTED, false);
        if (lastConnected == null || lastConnected != connected) {
            lastConnected = connected;
            sendBroadcast(new Intent(ACTION_CABLE_CHANGED)
                    .setPackage(getPackageName()).putExtra(EXTRA_CONNECTED, connected));
        }
        if (!connected) {
            announced = false;
            notifications.cancel(LINK_ID);
            return;
        }
        if (MainActivity.isResumed()) {
            notifications.cancel(LINK_ID);
            announced = true;
            return;
        }
        if (announced || !notifications.areNotificationsEnabled()) return;

        Intent open = new Intent(this, GpuLinkActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent prompt = PendingIntent.getActivity(this, LINK_ID, open, PendingIntent.FLAG_IMMUTABLE);
        Notification link = new Notification.Builder(this, CABLE_CHANNEL)
                .setSmallIcon(R.drawable.ic_status)
                .setContentTitle(getText(R.string.link_title))
                .setContentText(getText(R.string.link_notification))
                .setContentIntent(prompt)
                .setVisibility(Notification.VISIBILITY_PUBLIC).setAutoCancel(true)
                .setOnlyAlertOnce(true).build();
        try {
            notifications.notify(LINK_ID, link);
            announced = true;
        } catch (SecurityException denied) {
            // The USB state is still delivered to the visible activity.
        }
    }

    private void refreshPairing() {
        if (polling) return;
        polling = true;
        network.execute(() -> {
            try {
                JSONObject snapshot = client.getSnapshot();
                handler.post(() -> {
                    if (destroyed) return;
                    polling = false;
                    updatePairing(snapshot);
                    schedulePairingPoll();
                });
            } catch (IOException | JSONException failure) {
                handler.post(() -> {
                    if (destroyed) return;
                    polling = false;
                    // A failed read does not establish that the request was cleared.
                    schedulePairingPoll();
                });
            }
        });
    }

    private void schedulePairingPoll() {
        handler.removeCallbacks(poll);
        if (!destroyed) handler.postDelayed(poll, POLL_DELAY_MS);
    }

    private void updatePairing(JSONObject snapshot) {
        JSONObject gpu = snapshot.optJSONObject("gpu");
        JSONObject link = gpu == null ? null : gpu.optJSONObject("link");
        JSONObject pending = link == null ? null : link.optJSONObject("pending");
        if (pending == null) {
            clearPairing();
            return;
        }
        String code = pending.optString("code");
        if (!code.matches("[0-9]{6}")) {
            clearPairing();
            return;
        }
        if (!notifications.areNotificationsEnabled()
                || (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED)) {
            clearPairing();
            return;
        }
        String label = pending.optString("label").trim();
        if (code.equals(notifiedCode) && label.equals(notifiedLabel)) return;

        Intent open = new Intent(this, MainActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent prompt = PendingIntent.getActivity(this, PAIRING_ID, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        String formattedCode = code.substring(0, 3) + " " + code.substring(3);
        Notification pairing = new Notification.Builder(this, PAIRING_CHANNEL)
                .setSmallIcon(R.drawable.ic_status)
                .setContentTitle(label.isEmpty() ? getString(R.string.pairing_notification_title_unnamed)
                        : getString(R.string.pairing_notification_title, label))
                .setContentText(getString(R.string.pairing_notification_text, formattedCode))
                .setContentIntent(prompt)
                .setVisibility(Notification.VISIBILITY_PUBLIC)
                .setOnlyAlertOnce(true)
                .setTimeoutAfter(60000)
                .build();
        try {
            notifications.notify(PAIRING_ID, pairing);
            notifiedCode = code;
            notifiedLabel = label;
        } catch (SecurityException denied) {
            clearPairing();
        }
    }

    private void clearPairing() {
        if (notifiedCode == null) return;
        notifications.cancel(PAIRING_ID);
        notifiedCode = null;
        notifiedLabel = null;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        // Re-evaluate a cable already attached when the owner grants notifications.
        updateConnection(readUsbState());
        handler.removeCallbacks(poll);
        handler.post(poll);
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        destroyed = true;
        handler.removeCallbacks(poll);
        network.shutdownNow();
        clearPairing();
        unregisterReceiver(receiver);
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
